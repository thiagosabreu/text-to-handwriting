# Fontes humanizadas (ABNT2)

Fontes geradas por `scripts/gerar-fontes.py` a partir de fontes manuscritas sob a
SIL Open Font License 1.1 (veja `OFL.txt`). Todas cobrem Ç, acentos e os símbolos do
teclado ABNT2 (ª º ° § ¹ ² ³ £ ¢ ¬ ¨ etc.).

Cada letra/dígito tem 3 variantes extras (leve rotação, escala, linha de base e
traço tremido). A feature OpenType `calt` alterna entre elas, então letras
repetidas ("rr", "ss") nunca saem idênticas.

| Fonte       | Derivada de             | Copyright da base                          |
| ----------- | ----------------------- | ------------------------------------------ |
| Caderno     | Caveat                  | The Caveat Project Authors                 |
| Rascunho    | Kalam                   | Indian Type Foundry                        |
| Bilhete     | Patrick Hand            | Patrick Wagesreiter                        |
| Recado      | Indie Flower            | The Indie Flower Authors                   |
| Anotação    | Shadows Into Light Two  | Kimberly Geswein                           |
| Lousa       | Gochi Hand              | Huerta Tipográfica                         |
| Garrancho   | Reenie Beanie           | Typeco                                     |
| Diário      | Nothing You Could Do    | Kimberly Geswein                           |
| Cursiva BR  | Playwrite BR            | The Playwrite Project Authors              |

Para regerar (precisa de `fonttools` e `brotli`):

```bash
python scripts/gerar-fontes.py <pasta-com-as-fontes-base> fonts/humanizadas
```
