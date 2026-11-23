# mixed_lang sample

A deliberately polyglot mini-project so you can see Codex Cartographer map
many languages in **one** atlas:

| Folder   | Language        | What it shows                                        |
|----------|-----------------|------------------------------------------------------|
| `c/`     | C               | header + implementation, `#include` routes, `main`   |
| `cpp/`   | C++             | class hierarchy (`LinearModel : Model`), trainer loop |
| `matlab/`| MATLAB / Octave | script entry point + functions across sub-folders    |
| `java/`  | Java            | class with methods, `import` routes, `main`          |
| `go/`    | Go              | struct + methods + `import` block                    |
| `rust/`  | Rust            | `struct` + `impl` + free function                    |
| `r/`     | R               | `<- function` definitions, `library()` routes        |
| `julia/` | Julia           | `struct` + functions + `using`                       |

Run:

```bash
codex-cartographer samples/mixed_lang -o output/mixed_atlas.html
```
