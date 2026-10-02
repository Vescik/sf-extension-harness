// Run inside the existing vendor process, before its entrypoint. Authentication,
// connection lifecycle, MCP server, transport, and non-wiki tools stay with it.
import { register } from "node:module";

register(new URL("./ado_wiki_loader.mjs", import.meta.url), import.meta.url);
