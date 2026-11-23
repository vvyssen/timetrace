/*
 * Contents/MacOS/Timetrace — the main executable of the self-contained Timetrace.app.
 * Runs the Python bundled in Contents/Resources/python with `-I -m timetrace.macapp`, which installs
 * or repairs the background services and opens the dashboard (see src/timetrace/macapp.py).
 */
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(void) {
    char exe[PATH_MAX], real[PATH_MAX], contents[PATH_MAX], py[PATH_MAX];
    uint32_t n = sizeof exe;
    if (_NSGetExecutablePath(exe, &n) != 0 || !realpath(exe, real)) return 1;
    /* real = …/Timetrace.app/Contents/MacOS/Timetrace → …/Timetrace.app/Contents */
    strlcpy(contents, dirname(real), sizeof contents);
    strlcpy(contents, dirname(contents), sizeof contents);
    snprintf(py, sizeof py, "%s/Resources/python/bin/python3", contents);
    unsetenv("PYTHONHOME");
    unsetenv("PYTHONPATH");
    char *args[] = {py, "-I", "-m", "timetrace.macapp", NULL};
    execv(py, args);
    perror(py);
    return 1;
}
