-- Proxima Photos — Launch Script
set projectDir to "/Users/mike-j4c/Projects/proxima-image-library"
set logFile to "/tmp/proxima-server.log"

-- Ask user before launching
set answer to button returned of (display dialog "Launch Proxima Photos?" & return & return & "This will start a local server and open the app in your browser." buttons {"Cancel", "Open"} default button "Open" with title "Proxima Photos" with icon note)

if answer is "Cancel" then return

-- Kill any existing process on port 5000
do shell script "lsof -ti :5000 | xargs kill -9 2>/dev/null; true"

-- Start Flask in the background (no terminal window)
do shell script "cd " & quoted form of projectDir & " && nohup env TEST_MODE=true /usr/bin/python3 -m flask --app src.app run --port 5000 >> " & quoted form of logFile & " 2>&1 &"

-- Wait for server to be ready (poll up to 10 seconds)
set ready to false
repeat 10 times
	try
		do shell script "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/"
		set ready to true
		exit repeat
	end try
	delay 1
end repeat

if ready is false then
	display dialog "Server failed to start. Check /tmp/proxima-server.log for details." buttons {"OK"} default button "OK" with title "Proxima Photos" with icon caution
	return
end if

-- Open browser
open location "http://127.0.0.1:5000"
