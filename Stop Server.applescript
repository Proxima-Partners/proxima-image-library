
-- Stop Proxima Image Library server
do shell script "lsof -ti :5000 | xargs kill -9 2>/dev/null; true"
display notification "Proxima Image Library server stopped." with title "Proxima"

