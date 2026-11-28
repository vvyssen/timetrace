# dmgbuild settings for the Timetrace installer DMG (see scripts/make-dmg.sh).
# dmgbuild writes the Finder layout (.DS_Store) itself, so no Finder / AppleScript is needed,
# which keeps the build reliable on headless CI runners.
app = defines["app"]                     # path to Timetrace.app

volume_name = "Timetrace"
format = "ULFO"                          # LZFSE-compressed, read-only (macOS 10.11+)
filesystem = "HFS+"
files = [app]
symlinks = {"Applications": "/Applications"}
icon = defines["volume_icon"]            # the mounted volume shows the app icon

# Content area 600×360 pt, matching dmg/make-background.swift (icon centres at x 160 / 440, y 130).
# window_rect is the whole window; +28 pt for the title bar. Everything sits in the top 280 pt, so a
# Finder that also shows the tab bar and path bar still shows the whole layout without scrolling.
background = defines["background"]      # multi-resolution TIFF (1× + 2×)
window_rect = ((200, 160), (600, 388))
default_view = "icon-view"
show_status_bar = show_tab_view = show_toolbar = show_pathbar = show_sidebar = False
icon_size = 112
text_size = 13
icon_locations = {"Timetrace.app": (160, 130), "Applications": (440, 130)}
