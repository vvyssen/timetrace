/*
 * timetrace-importer — runs the iPhone/iPad Screen Time importer under this app bundle's privacy
 * identity, so Full Disk Access is granted to "Timetrace Importer.app" and nothing else (not to a
 * general-purpose Python interpreter).
 *
 * usage: timetrace-importer --status <status.json> -- <program> [args...]
 *
 * Until Full Disk Access is granted it does not start the importer: it re-checks every 30 seconds
 * and records the state in <status.json>, so the dashboard can tell the user what to do. The child
 * inherits this process as its "responsible" process, which is what macOS checks for privacy access.
 */
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern char **environ;
static pid_t child = 0;
static const char *status_path = NULL;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

static void write_status(int fda, const char *state, int code) {
    if (!status_path) return;
    char tmp[4096];
    snprintf(tmp, sizeof tmp, "%s.tmp", status_path);
    FILE *f = fopen(tmp, "w");
    if (!f) return;
    fprintf(f, "{\"fda\": %s, \"state\": \"%s\", \"exit_code\": %d, \"updated\": %ld, \"pid\": %d}\n",
            fda ? "true" : "false", state, code, (long)time(NULL), (int)getpid());
    fclose(f);
    rename(tmp, status_path);
}

/* 1 = readable, 0 = denied by privacy protection, -1 = not there (Screen Time sync not set up) */
static int probe(void) {
    const char *home = getenv("HOME");
    if (!home) return 0;
    char p[4096];
    snprintf(p, sizeof p, "%s/Library/Biome/sync/sync.db", home);
    int fd = open(p, O_RDONLY);
    if (fd >= 0) {
        close(fd);
        return 1;
    }
    if (errno == ENOENT) {
        snprintf(p, sizeof p, "%s/Library/Biome", home);
        fd = open(p, O_RDONLY);
        if (fd >= 0) {
            close(fd);
            return -1;
        }
        return errno == ENOENT ? -1 : 0;
    }
    return 0;
}

int main(int argc, char **argv) {
    int i = 1;
    for (; i < argc; i++) {
        if (strcmp(argv[i], "--status") == 0 && i + 1 < argc) {
            status_path = argv[++i];
        } else if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        }
    }
    if (i >= argc) {
        fprintf(stderr, "usage: %s --status <file> -- <program> [args...]\n", argv[0]);
        return 2;
    }

    for (;;) {
        int p = probe();
        if (p == 1) break;
        write_status(0, p == 0 ? "waiting-for-full-disk-access" : "no-screen-time-sync", 0);
        sleep(30);
    }
    write_status(1, "running", 0);

    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);
    int rc = posix_spawn(&child, argv[i], NULL, NULL, &argv[i], environ);
    if (rc != 0) {
        fprintf(stderr, "cannot start %s: %s\n", argv[i], strerror(rc));
        write_status(1, "spawn-failed", rc);
        return 1;
    }
    int st = 0;
    while (waitpid(child, &st, 0) < 0 && errno == EINTR) {
    }
    int code = WIFEXITED(st) ? WEXITSTATUS(st) : 128 + WTERMSIG(st);
    write_status(1, "exited", code);
    return code;
}
