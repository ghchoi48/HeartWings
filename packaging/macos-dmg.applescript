-- 배경과 아이콘 좌표는 scripts/build_desktop.py의 640×400 배경에 맞춘다.
on run arguments
    set mountFolder to POSIX file (item 1 of arguments) as alias
    set appName to item 2 of arguments
    tell application "Finder"
        tell folder (mountFolder as text)
            open
            set current view of container window to icon view
            set toolbar visible of container window to false
            set statusbar visible of container window to false
            set bounds of container window to {200, 150, 840, 572}
            set viewOptions to icon view options of container window
            set arrangement of viewOptions to not arranged
            set icon size of viewOptions to 96
            set text size of viewOptions to 14
            set label position of viewOptions to bottom
            set background picture of viewOptions to file ".background:install.png"
            set position of item appName to {170, 200}
            set position of item "Applications" to {470, 200}
            update without registering applications
            delay 2
            close
            -- Finder가 .DS_Store를 디스크에 기록할 시간을 확보한다.
            delay 2
        end tell
    end tell
end run
