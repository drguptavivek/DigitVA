
Docker/container-created files under /home/vivek/app/DigitVA/data/smartva_runs were owned by
  nobody:nogroup, with many nested directories at 700, so normal rsync as vivek could not read them.


Why normal rsync fails
  - pulling from laptop with remote sudo rsync failed because sudo wanted a TTY/password
  - pre-running ssh -t digitvaapp "sudo -v" did not help, because rsync opens a separate non-tty remote
    session

## Approach chosen:

Set up passwordless sudo for a narrowly scoped wrapper command, then use rsync normally from the laptop.

Server-side setup:
1. Confirm rsync path:
  
  `which rsync`
  Expected:
` /usr/bin/rsync`

  2. Create wrapper script:
  ```bash
  sudo tee /usr/local/bin/rsync-smartva-read >/dev/null <<'EOF'
  #!/bin/sh
  exec /usr/bin/rsync "$@"
  EOF
  ```

  `sudo chmod 755 /usr/local/bin/rsync-smartva-read`

  3. Add sudoers rule:

  `sudo visudo -f /etc/sudoers.d/rsync-smartva-read`

  Contents:

  `vivek ALL=(root) NOPASSWD: /usr/local/bin/rsync-smartva-read`

  4. Fix sudoers file ownership and mode:

```
  sudo chown root:root /etc/sudoers.d/rsync-smartva-read
  sudo chmod 0440 /etc/sudoers.d/rsync-smartva-read
```

  5. Validate sudoers:

  `sudo visudo -c`

  6. Validate passwordless access:

  `sudo -n /usr/local/bin/rsync-smartva-read --version`

  Expected:
  - prints rsync version
  - no password prompt

  Laptop-side rsync command used:

```
  rsync -avh --progress \
    --rsync-path="sudo /usr/local/bin/rsync-smartva-read" \
    digitvaapp:~/app/ \
    ./Digitva_server/
```

  Notes:
  -  macOS rsync did not support -A, so we used -avh --progress
  - trailing slash on ~/app/ means “copy contents of app”
  - rerunning the same command resumes efficiently and skips already copied files


##  Security note:

This setup gives vivek passwordless sudo for /usr/local/bin/rsync-smartva-read, which effectively
allows root-read access through that wrapper. It is narrower than allowing passwordless /usr/bin/rsync
directly, but it is still privileged access and should be treated accordingly.