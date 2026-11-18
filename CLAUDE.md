# research-tools

## Environment

Run repo commands in WSL with the conda env `research-tools` (`environment.yml`).
Each Bash call is a fresh shell and plain `conda activate` fails there, so use:

```bash
conda run --no-capture-output -n research-tools <command>
```

For several steps in one call: `eval "$(conda shell.bash hook)" && conda activate research-tools && ...`

- A Windows env (`research-tools-win` / `.venv-win`) also exists. Use it only where the README says so (e.g. `add_text_layer.py` OCR on Windows).
- GROBID and Ollama run on p1. Reach them over the network.
