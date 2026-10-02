// Contract: only a verified page-to-delivery relation is added, once. Real vendor
// registration is exercised; transport and SDK responses are isolated test data.
import test from "node:test";
import assert from "node:assert/strict";
import { configureWorkItemTools, createWikiLinkHandler } from "../../scripts/ado_wiki_link_tools.mjs";

const projectId = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const wikiId = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
const args = { project: "Example Project", workItemId: 123, linkType: "Wiki", wikiIdentifier: "Docs", pagePath: "/Delivery/Payment change" };
function fixture() {
  const state = { updates: [], scope: { organization: "example-org", project: args.project },
    wiki: { id: wikiId, projectId, name: "Docs", versions: [{ version: "wikiMaster" }] }, page: { path: args.pagePath, id: 42 },
    item: { id: 123, rev: 5, fields: { "System.TeamProject": args.project }, relations: [] } };
  const tracking = {
    getWorkItem: async (...parameters) => {
      assert.deepEqual(parameters, [123, undefined, undefined, 1, args.project]);
      return structuredClone(state.item);
    },
    updateWorkItem: async (headers, patch, id, project) => {
      assert.deepEqual(headers, {}); assert.equal(id, 123); assert.equal(project, args.project);
      state.updates.push(patch);
      if (state.failWrite) throw new Error("credential-like-error-must-not-escape");
      if (state.concurrentLinkBeforeWrite) {
        state.item.relations.push(structuredClone(patch[1].value));
        state.item.rev++;
        state.concurrentLinkBeforeWrite = false;
      }
      if (patch[0]?.value !== state.item.rev) throw new Error("JSON Patch revision test failed");
      assert.deepEqual(patch[0], { op: "test", path: "/rev", value: state.item.rev });
      assert.equal(patch.length, 2);
      state.item.relations.push(patch[1].value); state.item.rev++;
      if (state.timeoutAfterWrite) throw new Error("unknown write result");
      return structuredClone(state.item);
    },
  };
  const connection = { serverUrl: "https://dev.azure.com/example-org", getCoreApi: async () => ({ getProject: async () => ({ id: projectId, name: args.project }) }),
    getWikiApi: async () => ({ getWiki: async () => state.wiki }), getWorkItemTrackingApi: async () => tracking };
  const handler = createWikiLinkHandler(async () => "fake-token", async () => connection, () => "offline-test", {
    readScope: () => structuredClone(state.scope), fetch: async (url, options) => {
      assert.equal(url.origin, "https://dev.azure.com");
      assert.equal(url.searchParams.get("path"), args.pagePath); assert.equal(options.redirect, "error");
      assert.equal(url.searchParams.get("versionDescriptor.versionType"), "branch");
      assert.equal(url.searchParams.get("versionDescriptor.version"), state.wiki.versions[0].version);
      return new Response(JSON.stringify(state.page), { status: state.pageStatus ?? 200 });
    },
  });
  return { state, handler, connection };
}
const body = result => JSON.parse(result.content[0].text);

test("first link uses the existing Wiki Page relation, repeat performs no write", async () => {
  const { handler, state } = fixture();
  assert.equal(body(await handler(args)).status, "LINKED");
  assert.equal(body(await handler(args)).status, "UNCHANGED");
  assert.equal(state.updates.length, 1);
  assert.deepEqual(state.updates[0][1], { op: "add", path: "/relations/-", value: {
    rel: "ArtifactLink", url: `vstfs:///Wiki/WikiPage/${projectId}%2F${wikiId}%2FDelivery%2FPayment%20change`, attributes: { name: "Wiki Page" },
  } });
});

test("scope, missing page and wrong item prevent all writes", async () => {
  for (const mutate of [
    f => f.state.wiki.projectId = "cccccccc-cccc-cccc-cccc-cccccccccccc",
    f => f.state.item.fields["System.TeamProject"] = "Other Project",
    f => f.state.page.path = "/Other",
    f => f.state.pageStatus = 404,
    f => f.connection.serverUrl = "https://dev.azure.com/other-org",
    f => delete f.state.item.rev,
    f => delete f.state.wiki.versions,
    f => f.state.wiki.versions.push({ version: "future" }),
    f => f.state.wiki.versions[0].versionType = "commit",
    f => f.state.wiki.versions[0].versionOptions = "previousChange",
  ]) {
    const f = fixture(); mutate(f);
    assert.equal((await f.handler(args)).isError, true);
    assert.equal(f.state.updates.length, 0);
  }
});

test("raw artifact URI, extra selectors and unrelated link types are refused", async () => {
  for (const extra of [{ artifactUri: "vstfs:///Git/Ref/other" }, { projectId }, { linkType: "Branch" }, { pagePath: "/../Other" }, { workItemId: 1.5 }]) {
    const { handler, state } = fixture();
    assert.equal((await handler({ ...args, ...extra })).isError, true);
    assert.equal(state.updates.length, 0);
  }
});

test("conflict is not retried and uncertain success is deduplicated on retry", async () => {
  const conflict = fixture(); conflict.state.failWrite = true;
  const refused = await conflict.handler(args);
  assert.equal(refused.isError, true); assert.equal(body(refused).status, "UNVERIFIED");
  assert.equal(conflict.state.updates.length, 1);
  assert.ok(!JSON.stringify(refused).includes("credential-like"));
  const uncertain = fixture(); uncertain.state.timeoutAfterWrite = true;
  assert.equal((await uncertain.handler(args)).isError, true);
  assert.equal(body(await uncertain.handler(args)).status, "UNCHANGED");
  assert.equal(uncertain.state.updates.length, 1);
});

test("a concurrent addition causes a revision conflict and retry preserves the one relation", async () => {
  const { handler, state } = fixture();
  state.concurrentLinkBeforeWrite = true;
  assert.equal(body(await handler(args)).status, "UNVERIFIED");
  assert.equal(state.item.relations.length, 1);
  assert.equal(body(await handler(args)).status, "UNCHANGED");
  assert.equal(state.updates.length, 1);
  assert.equal(state.item.relations.length, 1);
});

test("existing hyperlink is retained with no duplicate ArtifactLink", async () => {
  const base = "https://dev.azure.com/example-org/Example%20Project/_wiki/wikis";
  for (const url of [
    `${base}/${wikiId}/42`,
    `${base}/Docs/42/Payment-change#deployment`,
    `${base}/Docs?pagePath=%2FDelivery%2FPayment%20change`,
    `${base}/${wikiId}?wikiVersion=GBwikiMaster&pagePath=%2fDelivery%2fPayment+change#manual-steps`,
    `${base}/%44ocs/42/Payment-change?pagePath=%2FDelivery%2FPayment%20change`,
    `https://dev.azure.com/example-org/${projectId}/_wiki/wikis/${wikiId}/42/Payment-change`,
  ]) {
    const { handler, state } = fixture();
    state.item.relations.push({ rel: "Hyperlink", url });
    assert.equal(body(await handler(args)).status, "UNCHANGED", url);
    assert.equal(state.updates.length, 0, url);
  }
});

test("existing artifact GUID case is normalized without folding the page path", async () => {
  const { handler, state } = fixture();
  state.item.relations.push({ rel: "ArtifactLink", url: `vstfs:///Wiki/WikiPage/${projectId.toUpperCase()}%2f${wikiId.toUpperCase()}%2fDelivery%2fPayment%20change` });
  assert.equal(body(await handler(args)).status, "UNCHANGED");
  assert.equal(state.updates.length, 0);
  state.item.relations[0].url = state.item.relations[0].url.replace("Delivery", "delivery");
  assert.equal(body(await handler(args)).status, "LINKED");
  assert.equal(state.updates.length, 1);
});

test("unrelated or ambiguous hyperlinks cannot suppress the verified Wiki relation", async () => {
  const base = "https://dev.azure.com/example-org/Example%20Project/_wiki/wikis";
  for (const url of [
    `${base}/OtherWiki/42/Payment-change`,
    `${base}/Docs/43/Payment-change`,
    `${base}/Docs?pagePath=%2FOther`,
    `${base}/Docs/42?pagePath=%2FOther`,
    `${base}/Docs?pagePath=%2FDelivery%2FPayment%20change&pagePath=%2FOther`,
    `${base}/Docs/42?wikiVersion=GBfuture`,
    `${base}/Docs/42?wikiVersion=GBwikiMaster&wikiVersion=GBfuture`,
    `${base}/Docs`,
    "https://dev.azure.com/other-org/Example%20Project/_wiki/wikis/Docs/42",
    "https://dev.azure.com/example-org/Other%20Project/_wiki/wikis/Docs/42",
    "https://dev.azure.com.evil.test/example-org/Example%20Project/_wiki/wikis/Docs/42",
  ]) {
    const { handler, state } = fixture();
    state.item.relations.push({ rel: "Hyperlink", url });
    assert.equal(body(await handler(args)).status, "LINKED", url);
    assert.equal(state.updates.length, 1, url);
    assert.equal(state.item.relations[0].url, url);
  }
});

test("vendor read registrations remain; only artifact-link schema is narrowed", () => {
  const registrations = new Map();
  configureWorkItemTools({ tool: (name, description, schema, callback) => registrations.set(name, { schema, callback }) },
    async () => { throw new Error("no auth during registration"); }, async () => { throw new Error("no network during registration"); }, () => "offline-test");
  assert.ok(registrations.has("wit_get_work_item"));
  assert.deepEqual(Object.keys(registrations.get("wit_add_artifact_link").schema).sort(), Object.keys(args).sort());
});
