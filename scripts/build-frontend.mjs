// SPDX-License-Identifier: GPL-3.0-or-later
import fs from "node:fs/promises";

const root = new URL("../", import.meta.url);
const json = async name => JSON.parse(await fs.readFile(new URL(name, root), "utf8"));
const manifest = await json("plugin.json"), metadata = await json("package.json");
const sources = await Promise.all(metadata.frontend.map(name => fs.readFile(new URL(name, root), "utf8")));
const header = `// Ayaneo 3 Decky ${metadata.version}. SPDX-License-Identifier: GPL-3.0-or-later\nconst PLUGIN_NAME = ${JSON.stringify(manifest.name)};\n`;
await fs.mkdir(new URL("dist/", root), { recursive: true });
await fs.writeFile(new URL("dist/index.js", root), header + sources.join("\n"));
