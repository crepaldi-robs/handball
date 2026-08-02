// Copia a fonte canônica de tokens para dentro deste pacote antes do build,
// para nunca duplicar hexadecimais à mão aqui. Nunca editar
// src/tokens.generated.css manualmente — ver README.md.
import { copyFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, "..", "..", "static", "css", "tokens.generated.css");
const destination = join(here, "..", "src", "tokens.generated.css");

copyFileSync(source, destination);
console.log(`Copiado ${source} -> ${destination}`);
