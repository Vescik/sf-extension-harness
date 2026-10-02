// Contract and regression tests against injected HTTP, without ADO credentials.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { z } from "zod";
import { configureWikiTools, createWikiHandlers } from "../../scripts/ado_wiki_tools.mjs";

const root = new URL("../../", import.meta.url);
const target = { project: "Project with spaces", wikiIdentifier: "Sample.wiki", path: "/Orders/Rule", branch: "wikiMaster" };
const scope = { organization: "example-org", project: target.project };
const baseUrl = "https://dev.azure.com/example-org";
const projectId = "11111111-1111-1111-1111-111111111111";
const wikiId = "22222222-2222-2222-2222-222222222222";
const connection = (serverUrl = baseUrl, project = {}) => ({ serverUrl,
  getCoreApi: async () => ({ getProject: async () => ({ id: projectId, name: scope.project, ...project }) }),
  getWikiApi: async () => ({ getWiki: async () => ({ id: wikiId, projectId }) }),
});
const page = (content = "Original", path = target.path) => ({ id: 7, path, content,
  remoteUrl: `${baseUrl}/Project%20with%20spaces/_wiki/wikis/Sample.wiki/7/Rule`, subPages: [] });
function response(status, body, etag = '"v1"') {
  return { status, headers: new Headers(etag === null ? {} : { etag }), json: async () => body };
}
function unpack(result) {
  const text = result.content[0].text;
  return JSON.parse(text.slice(text.indexOf("\n") + 1, text.lastIndexOf("\n")));
}
function fixture(responses = [], serverUrl = baseUrl) {
  const requests = [];
  const handlers = createWikiHandlers({
    tokenProvider: async () => "test-token", connectionProvider: async () => connection(serverUrl),
    userAgentProvider: () => "test-agent", scopeProvider: () => scope,
    fetchImpl: async (url, options) => {
      requests.push({ url, ...options });
      const next = responses.shift();
      assert.notEqual(next, undefined, "Unexpected HTTP request");
      if (next instanceof Error) throw next;
      return typeof next === "function" ? await next(url, options) : next;
    },
  });
  return { ...handlers, requests, responses };
}
const update = (extra = {}) => ({ ...target, content: "Updated", mode: "update", etag: '"v1"', ...extra });

test("full live read keeps all raw content and ETag from the same response", async () => {
  const content = "# Full\n" + "preserve <tag> & exact Unicode ą 😀\n".repeat(5000);
  const f = fixture([response(200, page(content))]);
  const result = await f.read(target);
  assert.equal(result.isError, undefined);
  assert.equal(unpack(result).page.content, content);
  assert.equal(unpack(result).etag, '"v1"');
  assert.equal(unpack(result).pageUrl, `${baseUrl}/Project%20with%20spaces/_wiki/wikis/${wikiId}/7`);
  const url = new URL(f.requests[0].url);
  assert.equal(url.searchParams.get("includeContent"), "true");
  assert.equal(url.searchParams.get("versionDescriptor.version"), "wikiMaster");
  assert.equal(url.searchParams.get("path"), target.path);
  assert.equal(f.requests[0].redirect, "error");
  assert.ok(f.requests[0].signal instanceof AbortSignal);
  assert.match(result.content[0].text, /UNTRUSTED WIKI PAGE CONTENT/u);
});

test("metadata recursion still requests the complete tree", async () => {
  const f = fixture([response(200, page())]);
  await f.read({ ...target, recursionLevel: "Full" });
  assert.equal(new URL(f.requests[0].url).searchParams.get("recursionLevel"), "Full");
});

test("empty content is complete; missing content, path, or ETag fails closed", async () => {
  assert.equal(unpack(await fixture([response(200, page(""))]).read(target)).page.content, "");
  for (const bad of [response(200, { path: target.path }), response(200, page(), null),
    response(200, page("Original", "/Different")), response(200, page(), "*"),
    response(200, page(), 'W/"weak"'), response(200, null)]) {
    const f = fixture([bad]);
    assert.equal(unpack(await f.read(target)).code, "INCOMPLETE_READ");
    assert.equal(f.requests.length, 1);
  }
});

test("only exact configured connection and target reach HTTP", async () => {
  for (const args of [{ ...target, project: "Another" }, { ...target, wikiIdentifier: "../wiki" },
    { ...target, path: "/Orders/../Other" }, { ...target, path: "/Orders//Other" },
    { ...target, path: "http://external.test/page" }, { ...target, branch: "refs/heads/../bad" },
    { ...target, branch: "*" }, { ...target, branch: "x\n" }]) {
    const f = fixture();
    assert.equal((await f.read(args)).isError, true);
    assert.equal(f.requests.length, 0);
  }
  for (const server of ["https://evil.test", `${baseUrl}/wrong`, "https://dev.azure.com/other-org"]) {
    const f = fixture([], server);
    assert.equal((await f.read(target)).isError, true);
    assert.equal(f.requests.length, 0);
  }
});

test("query URL decodes exactly once and ID URL never falls back to root", async () => {
  const urlBase = `${baseUrl}/Project%20with%20spaces/_wiki/wikis/Sample.wiki`;
  const f = fixture([response(200, page("Literal", "/%2Fspecial"))]);
  const result = await f.read({ url: `${urlBase}?pagePath=%2F%252Fspecial&wikiVersion=GBwikiMaster` });
  assert.equal(unpack(result).path, "/%2Fspecial");
  assert.equal(new URL(f.requests[0].url).searchParams.get("path"), "/%2Fspecial");
  const id = fixture([response(200, page()), response(200, page())]);
  assert.equal(unpack(await id.read({ url: `${urlBase}/7/Rule` })).path, target.path);
  assert.match(id.requests[0].url, /\/pages\/7\?/u);
  assert.equal(new URL(id.requests[1].url).searchParams.get("path"), target.path);
  for (const status of [401, 403, 404, 500]) {
    const bad = fixture([response(status, {})]);
    assert.equal((await bad.read({ url: `${urlBase}/7/Rule` })).isError, true);
    assert.equal(bad.requests.length, 1);
  }
  for (const badUrl of [`${urlBase}/7x/Rule`, `${urlBase}?pagePath=/A&pagePath=/B`,
    `${urlBase}?wikiVersion=GCcommit`, `${urlBase.replace("example-org", "other-org")}?pagePath=/A`]) {
    const f = fixture();
    assert.equal((await f.read({ url: badUrl })).isError, true);
    assert.equal(f.requests.length, 0);
  }
});

test("conditional update uses the original read ETag, preserves full content, and returns receipt", async () => {
  const content = "# New\n\nFull body <tag>\n";
  const f = fixture([response(200, page()), response(200, page(content), '"v2"')]);
  const result = await f.write(update({ content }));
  assert.equal(unpack(result).result, "updated");
  assert.equal(unpack(result).etag, '"v2"');
  assert.equal(f.requests.length, 2);
  assert.equal(f.requests[1].method, "PUT");
  assert.equal(f.requests[1].headers["If-Match"], '"v1"');
  assert.deepEqual(JSON.parse(f.requests[1].body), { content });
  assert.equal(f.requests[0].url, f.requests[1].url);
});

test("same-content update is a read-only no-op", async () => {
  const f = fixture([response(200, page())]);
  assert.equal(unpack(await f.write(update({ content: "Original" }))).result, "unchanged");
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].method, undefined);
});

test("stale ETag and deletion never adopt a new version or recreate", async () => {
  for (const state of [response(200, page("Concurrent edit"), '"v2"'), response(404, {})]) {
    const f = fixture([state]);
    assert.equal(unpack(await f.write(update())).code, "CONFLICT");
    assert.equal(f.requests.length, 1);
    assert.equal(f.requests[0].method, undefined);
  }
});

test("409/412 during conditional write return conflict without retry", async () => {
  for (const status of [409, 412]) {
    const f = fixture([response(200, page()), response(status, {})]);
    const result = await f.write(update());
    assert.equal(unpack(result).code, "CONFLICT");
    assert.equal(unpack(result).httpStatus, status);
    assert.equal(f.requests.length, 2);
  }
});

test("missing ETag, wildcard, ambiguous mode, or create ETag never reach HTTP", async () => {
  for (const args of [update({ etag: undefined }), update({ etag: "*" }), update({ etag: "a,b" }),
    update({ etag: 'W/"a"' }), update({ etag: '"old", *' }), update({ etag: "unquoted" }),
    update({ mode: undefined }), update({ mode: "create" }),
    update({ content: undefined }), update({ path: undefined }), update({ project: "Other" })]) {
    const f = fixture();
    assert.equal((await f.write(args)).isError, true);
    assert.equal(f.requests.length, 0);
  }
});

test("create requires absence and never falls through into update", async () => {
  const args = { ...target, mode: "create", content: "Created" };
  const f = fixture([response(404, {}), response(201, page("Created"))]);
  assert.equal(unpack(await f.write(args)).result, "created");
  assert.equal(f.requests[1].headers["If-Match"], undefined);
  assert.equal(f.requests[1].headers["If-None-Match"], "*");
  const exists = fixture([response(200, page("Created"))]);
  assert.equal(unpack(await exists.write(args)).code, "CONFLICT");
  assert.equal(exists.requests.length, 1);
  for (const status of [409, 412, 500]) {
    const race = fixture([response(404, {}), response(status, {})]);
    assert.equal((await race.write(args)).isError, true);
    assert.equal(race.requests.length, 2);
  }
});

test("read errors and partial preflight responses prevent writes", async () => {
  for (const state of [new Error("timeout"), response(403, {}), response(500, {}),
    response(200, { path: target.path }), response(200, page(), null)]) {
    const f = fixture([state]);
    assert.equal((await f.write(update())).isError, true);
    assert.equal(f.requests.length, 1);
  }
});

test("timeout and malformed success receipts preserve uncertain outcome; no retries", async () => {
  for (const state of [new Error("timeout after send"), response(200, {}), response(200, page("Wrong")),
    response(200, page("Updated"), null), response(201, page("Updated")), response(500, {})]) {
    const f = fixture([response(200, page()), state]);
    const result = await f.write(update());
    assert.equal(unpack(result).code, "OUTCOME_UNKNOWN");
    assert.match(unpack(result).message, /[Rr]ead the target/u);
    assert.equal(f.requests.length, 2);
  }
});

test("parallel writers keep their own ETags; only first conditional PUT succeeds", async () => {
  let current = page();
  let currentEtag = '"v1"';
  let readers = 0;
  let release;
  const bothRead = new Promise((resolve) => { release = resolve; });
  const requests = [];
  const handlers = createWikiHandlers({ scopeProvider: () => scope,
    tokenProvider: async () => "test", connectionProvider: async () => connection(), userAgentProvider: () => "test",
    fetchImpl: async (url, options) => {
      requests.push({ url, ...options });
      if (options.method !== "PUT") {
        const snapshot = response(200, { ...current }, currentEtag);
        if (++readers === 2) release();
        await bothRead;
        return snapshot;
      }
      if (options.headers["If-Match"] !== currentEtag) return response(412, {});
      current = page(JSON.parse(options.body).content);
      currentEtag = '"v2"';
      return response(200, current, currentEtag);
    },
  });
  const results = await Promise.all([handlers.write(update({ content: "Writer A" })), handlers.write(update({ content: "Writer B" }))]);
  assert.equal(results.filter((result) => !result.isError).length, 1);
  assert.equal(results.filter((result) => unpack(result).code === "CONFLICT").length, 1);
  assert.equal(current.content, "Writer A");
  assert.equal(requests.filter((request) => request.method === "PUT").length, 2);
  assert.ok(requests.filter((request) => request.method === "PUT").every((request) => request.headers["If-Match"] === '"v1"'));
});

test("only the three intended registrations change and mode is required", () => {
  const tools = new Map();
  configureWikiTools({ tool(name, description, schema, callback) { tools.set(name, { description, schema, callback }); } },
    async () => "", async () => ({}), () => "test");
  assert.equal(tools.size, 6);
  assert.deepEqual([...tools.keys()].sort(), ["wiki_create_or_update_page", "wiki_get_page", "wiki_get_page_content", "wiki_get_wiki", "wiki_list_pages", "wiki_list_wikis"]);
  const schema = z.object(tools.get("wiki_create_or_update_page").schema);
  assert.equal(schema.safeParse({ ...target, content: "x" }).success, false);
  assert.equal(schema.safeParse(update()).success, true);
  assert.ok(tools.get("wiki_get_page_content").schema.url);
});

test("preload maps vendor wiki import to adapter while original registration stays importable", () => {
  const source = `
    import { z } from 'zod';
    import { configureWikiTools as selected } from './node_modules/@azure-devops/mcp/dist/tools/wiki.js';
    import { configureWikiTools as adapter } from './scripts/ado_wiki_tools.mjs';
    import { configureWikiTools as original } from './node_modules/@azure-devops/mcp/dist/tools/wiki.js?harness-original';
    import { configureWorkItemTools as selectedWork } from './node_modules/@azure-devops/mcp/dist/tools/work-items.js';
    import { configureWorkItemTools as adapterWork } from './scripts/ado_wiki_link_tools.mjs';
    import { configureWorkItemTools as originalWork } from './node_modules/@azure-devops/mcp/dist/tools/work-items.js?harness-original';
    if (selected !== adapter || selected === original) process.exit(2);
    if (selectedWork !== adapterWork || selectedWork === originalWork) process.exit(3);
    const schemas = new Map();
    const server = {tool(name, description, schema) {schemas.set(name, schema)}};
    selected(server, async()=>{throw new Error('auth forbidden')}, async()=>{throw new Error('connection forbidden')}, ()=>'test');
    selectedWork(server, async()=>{throw new Error('auth forbidden')}, async()=>{throw new Error('connection forbidden')}, ()=>'test');
    if (!schemas.get('wiki_create_or_update_page').mode) process.exit(4);
    if (schemas.get('wit_add_artifact_link').artifactUri) process.exit(5);
    if (!schemas.get('wit_add_artifact_link').wikiIdentifier) process.exit(6);
    if (!schemas.has('wit_get_work_item') || !schemas.has('wiki_list_wikis')) process.exit(7);
    if (z.object(schemas.get('wiki_get_page_content')).parse({url:'https://dev.azure.com/org/project/_wiki/wikis/wiki?pagePath=/A&wikiVersion=GBmain'}).branch !== undefined) process.exit(8);
    process.stdout.write('selective-loader-ok');
  `;
  const result = spawnSync(process.execPath, ["--import", "./scripts/ado_wiki_preload.mjs", "--input-type=module", "-e", source], { cwd: root, encoding: "utf8", timeout: 15000 });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, "selective-loader-ok");
  assert.equal(JSON.parse(readFileSync(new URL("node_modules/@azure-devops/mcp/package.json", root))).version, "2.8.1");
});

test("URL read accepts configured project and branch selector without default disagreement", async () => {
  const f = fixture([response(200, page())]);
  const url = `${baseUrl}/Project%20with%20spaces/_wiki/wikis/Sample.wiki?pagePath=%2FOrders%2FRule&wikiVersion=GBmain`;
  const result = unpack(await f.read({ project: scope.project, url }));
  assert.equal(result.branch, "main");
  assert.equal(new URL(result.pageUrl).searchParams.get("wikiVersion"), "GBmain");
  assert.equal(new URL(f.requests[0].url).searchParams.get("versionDescriptor.version"), "main");
  for (const args of [{ url, project: "Wrong" }, { url, project: scope.project, branch: "wikiMaster" }, { url, project: scope.project, path: "/X" }]) {
    const invalid = fixture();
    assert.equal((await invalid.read(args)).isError, true);
    assert.equal(invalid.requests.length, 0);
  }
});

test("canonical URL uses configured project and exact path if page ID is absent", async () => {
  const value = page();
  delete value.id;
  value.remoteUrl = `${baseUrl}/${projectId}/_wiki/wikis/${wikiId}?pagePath=/Wrong`;
  const result = unpack(await fixture([response(200, value)]).read(target));
  assert.equal(new URL(result.pageUrl).pathname, `/example-org/Project%20with%20spaces/_wiki/wikis/${wikiId}`);
  assert.equal(new URL(result.pageUrl).searchParams.get("pagePath"), target.path);
});

test("both module replacements remain active through a real node_modules symlink", (t) => {
  const directory = mkdtempSync(join(tmpdir(), "wiki-adapter-symlink-"));
  try {
    mkdirSync(join(directory, "scripts"));
    for (const name of ["ado_wiki_loader.mjs", "ado_wiki_preload.mjs", "ado_wiki_tools.mjs", "ado_wiki_link_tools.mjs"]) {
      copyFileSync(new URL(`scripts/${name}`, root), join(directory, "scripts", name));
    }
    try {
      symlinkSync(fileURLToPath(new URL("node_modules/", root)), join(directory, "node_modules"), process.platform === "win32" ? "junction" : "dir");
    } catch (error) {
      if (process.platform === "win32" && ["EPERM", "EACCES", "ENOSYS"].includes(error.code)) {
        t.skip("Host does not permit symlinks/junctions");
        return;
      }
      throw error;
    }
    const script = `
      import {configureWikiTools as wiki} from './node_modules/@azure-devops/mcp/dist/tools/wiki.js';
      import {configureWikiTools as localWiki} from './scripts/ado_wiki_tools.mjs';
      import {configureWorkItemTools as links} from './node_modules/@azure-devops/mcp/dist/tools/work-items.js';
      import {configureWorkItemTools as localLinks} from './scripts/ado_wiki_link_tools.mjs';
      if (wiki !== localWiki || links !== localLinks) process.exit(2);
      const names = new Map();
      const server = {tool(name, description, schema) {names.set(name, schema)}};
      wiki(server, async()=>{}, async()=>{}, ()=>'test');
      links(server, async()=>{}, async()=>{}, ()=>'test');
      if (!names.get('wiki_create_or_update_page').mode || names.get('wit_add_artifact_link').artifactUri) process.exit(3);
      process.stdout.write('symlink-safe');
    `;
    const result = spawnSync(process.execPath, ["--import", "./scripts/ado_wiki_preload.mjs", "--input-type=module", "-e", script], { cwd: directory, encoding: "utf8", timeout: 15000 });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout, "symlink-safe");
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("wiki ownership and scope changes fail closed before writing", async () => {
  for (const invalidConnection of [connection(baseUrl, { id: "not-guid" }), connection(baseUrl, { name: "Wrong" }),
    { ...connection(), getWikiApi: async () => ({ getWiki: async () => ({ id: wikiId, projectId: "other" }) }) }]) {
    let requests = 0;
    const handlers = createWikiHandlers({ scopeProvider: () => scope, tokenProvider: async () => "test",
      connectionProvider: async () => invalidConnection, userAgentProvider: () => "test",
      fetchImpl: async () => { requests++; throw new Error("forbidden"); } });
    assert.equal((await handlers.write(update())).isError, true);
    assert.equal(requests, 0);
  }
  let currentScope = scope;
  let requests = 0;
  const handlers = createWikiHandlers({ scopeProvider: () => currentScope, tokenProvider: async () => "test",
    connectionProvider: async () => connection(), userAgentProvider: () => "test",
    fetchImpl: async () => { requests++; currentScope = { ...scope, project: "Changed" }; return response(200, page()); } });
  assert.equal((await handlers.write(update())).isError, true);
  assert.equal(requests, 1);
});
