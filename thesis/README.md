# Thesis (LaTeX)

IEEEtran document. Build from the repo root with `make thesis`, or here:

```sh
latexmk -pdf main.tex
```

`latexmk` ships with MacTeX / BasicTeX (macOS) and MiKTeX / TeX Live (Windows).

`sections/appendix.tex` expects a `prism-uploads/` folder (gantt chart PNG,
acceptance and counseling PDFs) next to `main.tex`; it is not in git.
