// Replace only two pinned vendor registration modules. The original modules remain
// available to each adapter through an explicit query suffix; no vendor file is edited.
import { realpathSync } from "node:fs";
import { resolve as resolvePath } from "node:path";
import { pathToFileURL } from "node:url";

// Node resolves symlinks before returning a module URL. Match that physical path
// so a shared node_modules directory cannot silently restore the unsafe callbacks.
const vendorRoot = realpathSync(new URL("../node_modules/@azure-devops/mcp/", import.meta.url));
const replacements = new Map([
  [pathToFileURL(resolvePath(vendorRoot, "dist/tools/wiki.js")).href,
    new URL("./ado_wiki_tools.mjs", import.meta.url).href],
  [pathToFileURL(resolvePath(vendorRoot, "dist/tools/work-items.js")).href,
    new URL("./ado_wiki_link_tools.mjs", import.meta.url).href],
]);

export async function resolve(specifier, context, nextResolve) {
  const resolved = await nextResolve(specifier, context);
  const replacement = replacements.get(resolved.url);
  return replacement ? { ...resolved, url: replacement } : resolved;
}
