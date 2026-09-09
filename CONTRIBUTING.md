# Contributing to GTExplorer

Thanks for your interest in contributing! GTExplorer is a community tool for extracting, viewing, editing, and repacking Gran Turismo 1 (PS1) archive files, and there's plenty of room to help — from fixing bugs to tackling the bigger known limitations below.

## Getting Started

1. Fork the repo and clone your fork:
   ```
   git clone https://github.com/<your-username>/GTExplorer.git
   cd GTExplorer
   ```
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Run the app to confirm your environment works:
   ```
   python src/main.py
   ```
4. Complete first-launch **Setup** (input/output folders) as described in the [README](README.md#requirements--quick-start). If you're testing archive extraction/repacking, you'll need your own GT1 disc image or archive files — none are distributed with this project.

## Making Changes

1. Create a branch off `main`:
   ```
   git checkout -b fix/short-description
   ```
   or `feature/short-description` for new functionality.
2. Keep PRs focused — one bug fix or feature per PR makes review much easier.
3. For anything non-trivial (new features, UI changes, format-parsing changes), please open an issue first to discuss the approach before investing a lot of time.
4. Test your changes against real GT1 archive files where possible, especially for extraction/repacking logic — corrupted output is easy to miss without a real round-trip test.
5. Commit with clear, descriptive messages explaining *why*, not just *what*.
6. Push your branch and open a Pull Request against `main`, describing what changed and how you tested it.

## Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/) conventions.
- Match the existing structure of the codebase (PyQt6 widgets, editors, and format parsers are organized by feature — keep new code in the appropriate module rather than adding one-off scripts).
- Prefer clear, commented code over cleverness, especially in format-parsing code. Many of GT1's file formats aren't fully understood yet and are still under active research, so document your assumptions, note any unknowns or guesses inline, and explain how you verified a given interpretation (e.g. by testing against real archive files). This makes it far easier for others to pick up where you left off.
- Use type hints where practical.

## Areas That Need Help

These are pulled from the README's [Known Limitations](README.md#known-limitations) section and are great places to start:


- **TIM Pack Repacking** — `.tpk` repacking isn't implemented yet; only loose `.TIM` files can currently be edited and repacked.
- **Model Renderer** — the 3D model viewer is experimental. Models are missing wheels (placeholders are used) and there are known performance/crash issues.
- **Repack Workflow UX** — currently requires manually opening the target folder via **File → Open Folder** before repacking; a smoother workflow would help.
- **Disc Rebuilding Reliability** — automatic rebuilding via `mkpsxiso` can fail after repacking; improving reliability or error handling here would be valuable.

If you're not sure where to start, check the [Issues](https://github.com/JeevesGB/GTExplorer/issues) tab for open items, or open a new issue describing what you'd like to work on.

## Reporting Bugs

When filing a bug report, please include:
- Your OS and Python version
- The archive/file you were working with (or its type, e.g. `COURSE.DAT`)
- Steps to reproduce
- Any error output or screenshots



## Documentation

Improvements to the [User Guide](doc/usage.md), [format documentation](doc/formats.md), or this file are welcome too — documentation PRs don't need a prior issue.

## Credits

If your contribution builds on prior research (e.g. from [pez2k/gt2tools](https://github.com/pez2k/gt2tools)), please note that in your PR description so it can be credited appropriately.

## License

By contributing, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).