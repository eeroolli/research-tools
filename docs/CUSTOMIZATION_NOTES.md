# Customization Notes

## Conda Installation Location

The scanner launcher scripts (`scripts/start_scanner_daemon.bat` and `scripts/start_scanner_daemon.ps1`) assume conda/miniconda is installed in the standard location:

```
~/miniconda3/
```

### If Your Conda is Installed Elsewhere

**For anaconda instead of miniconda:**
Change `~/miniconda3/` to `~/anaconda3/` in both scripts:

**In `scripts/start_scanner_daemon.bat` (line 23):**
```batch
wsl bash -c "source ~/anaconda3/etc/profile.d/conda.sh && conda activate research-tools && python /mnt/f/prog/research-tools/scripts/start_paper_processor.py"
```

**In `scripts/start_scanner_daemon.ps1` (line 24):**
```powershell
$result = wsl bash -c "source ~/anaconda3/etc/profile.d/conda.sh && conda activate research-tools && python /mnt/f/prog/research-tools/scripts/start_paper_processor.py"
```

### If Conda Environment Has Different Name

If you named your environment something other than `research-tools`, change both occurrences in each script:

```bash
conda activate YOUR_ENVIRONMENT_NAME
```

---

## Project Location

The scripts use absolute paths to `/mnt/f/prog/research-tools/`. If you move the project:

1. Update paths in **both** launcher scripts
2. Update paths in `config.personal.conf`
3. Update scanner destination in Epson Capture Pro

---

## Scanner Destination

The daemon watches:
```
/mnt/i/FraScanner/papers/
```

**Windows path:** `I:\FraScanner\papers\`

If your scanner saves to a different location, update:
1. `config.personal.conf` → `scanner_papers_dir`
2. Epson Capture Pro → Scan Destination

---

## Zotero Database Location

The local search uses:
```
/mnt/f/prog/scanpapers/data/zotero.sqlite.bak
```

**Windows path:** `F:\prog\scanpapers\data\zotero.sqlite.bak`

If your Zotero database is elsewhere, update:
1. `config.personal.conf` → `zotero_db_path`

To find your Zotero database:
- Open Zotero
- Edit → Preferences → Advanced → Files and Folders → Data Directory Location
- The database is `zotero.sqlite` in that directory

**Note:** Consider using a backup copy (`.bak`) to avoid any locking issues.

---

## Publications Directory

Final PDFs are saved to:
```
/mnt/g/My Drive/publications/
```

**Windows path:** `G:\My Drive\publications\`

If you want PDFs saved elsewhere, update:
1. `config.personal.conf` → `publications_dir`

---

## Quick Customization Checklist

When setting up on a new machine or with different paths:

- [ ] Verify conda location (`~/miniconda3/` or `~/anaconda3/`)
- [ ] Update conda path in `scripts/start_scanner_daemon.bat`
- [ ] Update conda path in `scripts/start_scanner_daemon.ps1`
- [ ] Verify project location (`/mnt/f/prog/research-tools/`)
- [ ] Update `scanner_papers_dir` in `config.personal.conf`
- [ ] Update `publications_dir` in `config.personal.conf`
- [ ] Update `zotero_db_path` in `config.personal.conf`
- [ ] Test: `F:\prog\research-tools\scripts\start_scanner_daemon.bat`

---

## Testing Your Configuration

**From Windows Command Prompt:**

```cmd
REM Test conda activation
wsl bash -c "source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && python --version"

REM Test the batch file
F:\prog\research-tools\scripts\start_scanner_daemon.bat

REM Verify paths
wsl cat /mnt/f/prog/research-tools/config.personal.conf | grep -E "scanner|publications|zotero"
```

**Expected output:**
- Python version from conda environment
- Daemon starts (or "already running")
- Paths show correct locations

---

## Common Issues

### "conda: command not found"
- Your conda is not in `~/miniconda3/`
- Find it: `wsl which conda`
- Update paths in launcher scripts

### "research-tools: not found"
- Environment name is different
- Check: `wsl conda env list`
- Update environment name in launcher scripts

### "Permission denied"
- Make sure you're using WSL paths (`/mnt/f/...`) not Windows paths (`F:\...`)
- Check file permissions: `wsl ls -la /mnt/f/prog/research-tools/scripts/`

### "Database not found"
- Verify: `wsl ls -la /mnt/f/prog/scanpapers/data/zotero.sqlite.bak`
- Update path in `config.personal.conf`

---

All customizable settings are consolidated in `config.personal.conf` - edit that file first!

