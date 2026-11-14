# segl operator notes

How to install segl on Ubuntu 26.04, put nginx in front of it, and run it. The package installs this file as `/usr/share/doc/segl/OPERATOR.md`. The full manual is at <https://robert-patrick-texas.github.io/segl/docs/DEPLOY.html>.

## What segl is, and is not

- segl serves nine shared drawing boards, slots 1 to 9. Everyone who can open a slot sees it live.
- The slots are shared. There are no accounts and no private boards. Do not put anything on a slot that not everyone who can reach segl may see.
- Protected inventory is not available on the slots. It belongs to a later release, behind a login.
- segl is for an internal network. Do not put it on the open internet, except as a demo with no real data.

## What the package installs

| Path | Contents |
|---|---|
| `/opt/segl/python` | CPython, pinned and installed by uv when the package was built. segl does not use the system's Python. |
| `/opt/segl/venv` | The virtualenv, from `uv.lock`, with the `segl` command. |
| `/opt/segl/app/web/dist` | The built web application. |
| `/opt/segl/share` | The nginx files, the two files `/opt/segl/etc` starts from, and the keys a release may be signed with. |
| `/opt/segl/etc/segl.toml` | The settings. Mode `0640`, owner `root`, group `segl`. |
| `/opt/segl/etc/display-names.txt` | The words new visitors are named from. |
| `/opt/segl/var` | The database and the uploaded images. Only user `segl` writes here. |
| `/opt/segl/update` | What `segl update` keeps: downloaded packages, and copies of the settings and the database. Only root opens it. |
| `/usr/bin/segl` | The `segl` command. |
| `/usr/lib/systemd/system/segl.service` | The unit. It runs segl as user `segl`. |
| `/usr/lib/systemd/system/segl-update.timer` | The nightly update. Off until you turn it on. |
| `/usr/share/doc/segl` | These notes, `LICENSE`, `NOTICE`, and the licenses of the bundled parts. |

The package creates system user `segl`. It creates the two files in `/opt/segl/etc` only when they are missing. An upgrade never replaces them. It adds new settings to `segl.toml` and keeps every line you wrote.

## Install and start

```bash
sudo apt install ./segl_<version>_amd64.deb
sudo systemctl enable --now segl
systemctl status segl
curl http://127.0.0.1:8888/api/v1/health
```

The install starts nothing. `enable --now` starts segl, now and at every boot. The last command answers `{"status":"ok"}`.

segl listens on `127.0.0.1:8888` only. nginx faces the network.

## nginx

Install nginx, then the three segl files. This mounts segl at `/board/` on a site you already have:

```bash
sudo install -m 644 /opt/segl/share/nginx/segl-http.conf  /etc/nginx/conf.d/segl.conf
sudo install -m 644 /opt/segl/share/nginx/segl-proxy.conf /etc/nginx/snippets/segl-proxy.conf
sudo install -m 644 /opt/segl/share/nginx/segl-board.conf /etc/nginx/snippets/segl-board.conf
```

Add one line inside the site's `server { }` block:

```nginx
include snippets/segl-board.conf;
```

Then check and reload:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Slot 1 is now at `https://<your site>/board/s/1`.

No site yet? Start from an example. `site-board.example.conf` is a whole TLS site with segl at `/board/`. `site-root.example.conf` gives segl a host name of its own.

```bash
sudo install -m 644 /opt/segl/share/nginx/site-board.example.conf /etc/nginx/sites-available/dev.example.com
sudo ln -s ../sites-available/dev.example.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Change `dev.example.com` to your host name, in the file and in its name. Both examples use Ubuntu's self-signed snakeoil certificate (package `ssl-cert`). Replace it with the site's own. Ports, TLS, and headers are the site's to set.

## Settings

Edit `/opt/segl/etc/segl.toml`, then restart:

```bash
sudo systemctl restart segl
```

Every key has a comment in the file. A key segl does not know, or a value it cannot use, stops it. `systemctl status segl` shows the line that names the key. Fix the file and start segl again.

### Who can edit

As installed, `access_codes = []`: anyone who can open a slot can edit it.

To limit editing, set one or more codes and a secret:

```toml
access_codes = ["maple river 42", "Night shift 1836"]
access_secret = "<what `openssl rand -base64 32` wrote>"
```

- A code has at least 8 letters and digits. Case, spaces, and punctuation do not matter when a person types it.
- A person without a code still watches live. The bar shows `Enter access code`.
- A right code lets that browser edit for `access_pass_hours` (12). Then the person enters a code again.
- To end one group's access, take its code out of the list and restart.
- Keep the file at mode `0640`, owner `root`, group `segl`.

The access page is not a login. A code is shared, and segl does not know who entered it. It keeps honest people from changing a board by mistake. It does not keep a determined person out.

### End every pass

To make every browser enter a code again, while the codes still work:

```bash
date -u +%Y-%m-%dT%H:%M:%SZ
```

Put that time in `access_passes_after` and restart segl. A new `access_secret` does the same.

### Who can reach segl

As installed, `internal_networks = []`: segl answers every address that reaches it.

To answer only your own networks:

```toml
internal_networks = ["10.0.0.0/8", "192.168.4.0/24"]
```

Everyone else gets `403`. A firewall, or the `allow` and `deny` lines in `segl-board.conf`, is the first place for this. `internal_networks` is the second check.

With nginx on another host, list that host in `trusted_proxies`. Otherwise every visitor looks like the proxy.

### Display names

New visitors are named from `/opt/segl/etc/display-names.txt`: `Alpha1`, `Bravo2`, and so on. To use your own words, replace the file's contents: one word on a line, 1 to 10 letters. Then restart segl.

## Back up

The boards are in `/opt/segl/var`: the database and the images. Back them up together:

```bash
sudo systemctl stop segl
sudo cp -a /opt/segl/var /your/backup/segl-var
sudo systemctl start segl
```

Back up `/opt/segl/etc` too.

## Update

```bash
segl update --check    # is a newer release out? It changes nothing
sudo segl update       # install it, after asking
```

`segl update` downloads the newest release from GitHub and checks its signature. Then it:

1. Stops segl, and saves the settings, the nginx files, and the database.
2. Installs the package.
3. Adds the new version's settings to `segl.toml`, and merges its nginx changes into your files in `/etc/nginx`. Every line you wrote stays.
4. Checks the settings and runs `nginx -t`.
5. Starts segl, and reloads nginx if an nginx file changed.

If a step fails, it puts the previous version back, with your files as they were, and says which step failed. segl is down for some seconds while the package installs. Browsers reconnect by themselves.

More options:

```bash
sudo segl update --yes                      # do not ask
sudo segl update --version <version>        # that release, also an older one
sudo segl update --proxy=http://proxy.example.com:3128/
sudo segl update --from /root/segl-<version>
```

- **Proxy.** `--proxy` is for one run. For every run, set `update_proxy` in `segl.toml`.
- **A firewall that inspects TLS.** `segl update` refuses its certificate and says so. Install the firewall's CA: copy it as a `.crt` file to `/usr/local/share/ca-certificates/` and run `sudo update-ca-certificates`.
- **No way out to GitHub.** Download the release's three files on another machine: the `.deb`, `SHA256SUMS`, and `SHA256SUMS.sig`. Copy them into one folder on the server and use `--from`.

### Update every night

The nightly update is off as installed. To turn it on:

```bash
sudo systemctl enable --now segl-update.timer
```

Each night it checks once, at a random time from 21:00 to 03:00, server time. It installs a newer release as above. It does not try a release again after that release failed.

```bash
systemctl list-timers segl-update.timer   # the next run
journalctl -u segl-update                 # what each run did
sudo systemctl disable --now segl-update.timer   # off again
```

### Upgrade by hand

```bash
sudo apt install ./segl_<new version>_amd64.deb
```

This keeps the settings and the boards, merges new statements as an update does, and restarts segl if it was running. It checks no signature and does not go back if the new version fails.

## Stop and remove

A stop writes every unsaved edit first:

```bash
sudo systemctl stop segl
```

`sudo apt remove segl` removes the program and keeps `/opt/segl/etc`, `/opt/segl/var`, and `/opt/segl/update`. `sudo apt purge segl` also removes the settings and the update folder. It keeps the boards, and says so. To delete them, remove `/opt/segl`.

## When something is wrong

```bash
systemctl status segl
journalctl -u segl -e
```

- **segl does not start.** The journal's last lines name the cause: a setting, the database, the display-name file, or the image folder.
- **`start ... was attempted too often`.** systemd allows five starts in a minute. Fix the cause, then run `sudo systemctl reset-failed segl` and start segl again.
- **`502 Bad Gateway`.** segl is not running, or `bind` and the upstream in `/etc/nginx/conf.d/segl.conf` differ.
- **The page says `Disconnected`.** segl stopped, or nginx is not passing the WebSocket. Check that `conf.d/segl.conf` and `snippets/segl-proxy.conf` are the files from `/opt/segl/share/nginx`.
- **An update failed.** `segl update` says which step failed, and `journalctl -u segl-update` has the same for a nightly run. The previous version is back. `/opt/segl/update/last-update.json` has the reason.
- **`changed the same lines`.** You and the new release changed the same lines of an nginx file. Compare your file with the one in `/opt/segl/share/nginx`, merge it by hand, and update again.
- **`cannot open the database` after you moved it.** The unit lets segl write in `/opt/segl/var` alone. For another folder, run `sudo systemctl edit segl`, add the two lines below, and restart.

```ini
[Service]
ReadWritePaths=/srv/segl
```
