# Troubleshooting Adjudicator

During an event, the admin/gold team can temporarily enable deep debugging modes on a specific health node to see exactly what the Adjudicator is seeing over the wire. This is useful for gaining insight into why checks are passing or failing for a specific team and service.

## Procedure to Troubleshoot Service Checks

### 1. Enable Debug Logging and Raw Data Saves
SSH into the specific health node running the adjudicator and edit the systemd service file (typically located at `/etc/systemd/system/scorebot-monitor.service`, or adjust via the `ansible-role-health` deployment).

Change the environment variables from this:
```ini
Environment="LOG_LEVEL=INFO"
Environment="SAVE_DATA=FALSE"
```
To this:
```ini
Environment="LOG_LEVEL=DEBUG"
Environment="SAVE_DATA=TRUE"
```

### 2. Restart the Monitor Service
Apply the changes and restart the Adjudicator process:
```bash
sudo systemctl daemon-reload
sudo systemctl restart scorebot-monitor
```

### 3. Inspect Real-time Debug Logs
Watch the exact progression of every job. The `DEBUG` log level will show if the connection failed, if authentication failed, or if an unexpected HTTP code was received.
```bash
sudo journalctl -u scorebot-monitor -f
```
*(Tip: You can pipe this through `grep` using the specific IP of the team or the specific port/service you are diagnosing to filter out the noise).*

### 4. Inspect the Raw Network Data
By setting `SAVE_DATA=TRUE`, the Adjudicator will dump the exact raw payloads it receives from the teams' services to disk. This is the ultimate "source of truth" if a team claims their service is returning the right content but the Adjudicator fails it.

You can find these files in the working directory (typically `/home/monitor/scorebot/code/`):
* `raw/<date>_Job_<jobid>_data`: The raw network response data received from the team's machine.
* `sbe/<date>_<time>.out`: Large HTML/JSON responses from the Scorebot Engine (useful if SBE is refusing the adjudicator's job submissions).

### 5. Revert When Finished
Leaving these settings on will flood the system journal and quickly fill up the disk with raw job data. Once you have your insight, change the variables back to `LOG_LEVEL=INFO` and `SAVE_DATA=FALSE`, then daemon-reload and restart the service again.
