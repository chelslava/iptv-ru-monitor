@echo off
rem Wrapper for Windows Task Scheduler: night RU probe (home-ru).
rem Task: "iptv-ru-monitor home-ru probe", daily 03:40 local time.
cd /d D:\Repo\iptv-ru-monitor
"C:\Program Files\Git\bin\bash.exe" -l -c "bash scripts/ru_probe_push.sh >> data/state/home-ru-task.log 2>&1"
