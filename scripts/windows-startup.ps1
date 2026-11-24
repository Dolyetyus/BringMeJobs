$ErrorActionPreference = "Stop"

$Distro = "Ubuntu"
$Repository = "/mnt/c/Users/dolia/Desktop/Portfolio/BringMeJobs"
$WebUrl = "http://127.0.0.1:6767/"

# Start the local dashboard first and wait until it responds.
$StartServerCommand = @"
cd '$Repository' || exit 1
if ! python3 -c 'import urllib.request; urllib.request.urlopen("$WebUrl", timeout=2).read(1)' >/dev/null 2>&1; then
  nohup python3 bringmejobs.py serve >>/tmp/bringmejobs-web.log 2>&1 </dev/null &
fi

for ((attempt = 0; attempt < 30; attempt++)); do
  if python3 -c 'import urllib.request; urllib.request.urlopen("$WebUrl", timeout=2).read(1)' >/dev/null 2>&1; then
    exit 0
  fi
  sleep 1
done

echo "BringMeJobs web server did not become available."
exit 1
"@

& wsl.exe -d $Distro -- bash -lc $StartServerCommand
if ($LASTEXITCODE -ne 0) {
    throw "Unable to start BringMeJobs web interface (WSL exit code $LASTEXITCODE)."
}

# Give Windows and the user a minute before starting external careers requests.
Start-Sleep -Seconds 60

& wsl.exe -d $Distro -- bash -lc "cd '$Repository' && python3 -m src.dispatcher"
if ($LASTEXITCODE -ne 0) {
    throw "BringMeJobs automation failed (WSL exit code $LASTEXITCODE)."
}
