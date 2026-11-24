$ErrorActionPreference = "Stop"

$Distro = "Ubuntu"
$Repository = "/mnt/c/Users/dolia/Desktop/Portfolio/BringMeJobs"

# Run the automation at Windows startup, then leave the local server running.
wsl.exe -d $Distro -- bash -lc "cd '$Repository' && python3 -m src.dispatcher"
wsl.exe -d $Distro -- bash -lc "cd '$Repository' && nohup python3 bringmejobs.py serve >/tmp/bringmejobs.log 2>&1 &"
