// Narrow the existing vendor relation tool; retain vendor authentication and all reads.
import { readFileSync } from "node:fs";
import { z } from "zod";
import { configureWorkItemTools as configureVendorTools } from "../node_modules/@azure-devops/mcp/dist/tools/work-items.js?harness-original";

const CONFIG = new URL("../config/harness.local.json", import.meta.url);
const GUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/iu;
const hasControl = value => [...value].some(char => char.codePointAt(0) < 32 || char.codePointAt(0) === 127);
const text = z.string().min(1).refine(value => value === value.trim() && !hasControl(value));
export const linkSchema = {
  project: text,
  workItemId: z.number().int().positive(),
  linkType: z.literal("Wiki"),
  wikiIdentifier: text,
  pagePath: text.refine(value => value.startsWith("/") && value !== "/" &&
    !value.includes("\\") && !value.includes("//") &&
    !value.split("/").some(part => part === "." || part === "..")),
};

function receipt(status, details = {}, isError = false) {
  return { content: [{ type: "text", text: JSON.stringify({ status, ...details }) }], ...(isError ? { isError: true } : {}) };
}

function readScope() {
  const ado = JSON.parse(readFileSync(CONFIG, "utf8")).ado;
  if (!ado || !/^[A-Za-z0-9][A-Za-z0-9-]*$/u.test(ado.organization) ||
      typeof ado.project !== "string" || !ado.project.trim() || ado.project !== ado.project.trim() ||
      hasControl(ado.project) || /[/\\]/u.test(ado.project) ||
      !ado.allowedHttpsOrigins?.includes(`https://dev.azure.com/${ado.organization}`)) {
    throw new Error("Invalid ADO scope");
  }
  return { organization: ado.organization, project: ado.project };
}

function sameArtifact(left, right) {
  const identity = value => {
    const decoded = decodeURIComponent(value);
    const match = /^vstfs:\/\/\/Wiki\/WikiPage\/([^/]+)\/([^/]+)\/(.+)$/u.exec(decoded);
    return match && GUID.test(match[1]) && GUID.test(match[2])
      ? `${match[1].toLowerCase()}/${match[2].toLowerCase()}/${match[3]}` : null;
  };
  try { const expected = identity(right); return expected !== null && identity(left) === expected; }
  catch { return false; }
}

function samePageHyperlink(value, scope, project, wiki, page, requestedWiki, branch) {
  if (typeof value !== "string" || value.includes("\\")) return false;
  try {
    const url = new URL(value);
    const parts = url.pathname.split("/").filter(Boolean).map(decodeURIComponent);
    if (url.protocol !== "https:" || url.hostname !== "dev.azure.com" || url.username || url.password || url.port ||
        parts.length < 5 || parts[0] !== scope.organization ||
        (parts[1] !== scope.project && parts[1].toLowerCase() !== project.id.toLowerCase()) ||
        parts[2] !== "_wiki" || parts[3] !== "wikis" ||
        parts.slice(0, 6).some(part => hasControl(part) || /[/\\]/u.test(part))) return false;
    const matchesWiki = parts[4].toLowerCase() === wiki.id.toLowerCase() ||
      [wiki.name, requestedWiki].filter(value => typeof value === "string").includes(parts[4]);
    if (!matchesWiki) return false;
    const paths = url.searchParams.getAll("pagePath");
    const versions = url.searchParams.getAll("wikiVersion");
    if (paths.length > 1 || versions.length > 1) return false;
    // A hyperlink to another branch is not proof of a link to the published page.
    if (versions.length && versions[0] !== `GB${branch}`) return false;
    const hasId = parts.length > 5;
    if (hasId && (!/^[1-9][0-9]*$/u.test(parts[5]) || Number(parts[5]) !== page.id)) return false;
    if (paths.length && paths[0] !== page.path) return false;
    return hasId || paths.length === 1;
  } catch {
    return false;
  }
}

export function createWikiLinkHandler(tokenProvider, connectionProvider, userAgentProvider, options = {}) {
  const scopeReader = options.readScope ?? readScope;
  const request = options.fetch ?? ((...args) => globalThis.fetch(...args));
  return async input => {
    let writeAttempted = false;
    try {
      const args = z.object(linkSchema).strict().parse(input);
      const scope = scopeReader();
      if (args.project !== scope.project) return receipt("BLOCKED", { reason: "Project scope mismatch" }, true);
      const connection = await connectionProvider();
      const origin = `https://dev.azure.com/${scope.organization}`;
      if (connection.serverUrl.replace(/\/$/u, "") !== origin) return receipt("BLOCKED", { reason: "Organization scope mismatch" }, true);
      const core = await connection.getCoreApi();
      const project = await core.getProject(scope.project);
      const wikiApi = await connection.getWikiApi();
      const wiki = await wikiApi.getWiki(args.wikiIdentifier, args.project);
      if (!GUID.test(project?.id) || !GUID.test(wiki?.id) ||
          wiki.projectId?.toLowerCase() !== project.id.toLowerCase() || project.name !== scope.project) {
        return receipt("BLOCKED", { reason: "Wiki does not belong to the configured project" }, true);
      }
      const version = wiki.versions?.length === 1 ? wiki.versions[0] : undefined;
      const branch = version?.version;
      if (typeof branch !== "string" || !branch || branch !== branch.trim() || hasControl(branch) ||
          ![undefined, 0, "branch"].includes(version.versionType) ||
          ![undefined, 0, "none"].includes(version.versionOptions)) {
        return receipt("INCOMPLETE", { reason: "The wiki's single published branch could not be established" }, true);
      }
      const endpoint = new URL(`${origin}/${encodeURIComponent(scope.project)}/_apis/wiki/wikis/${encodeURIComponent(wiki.id)}/pages`);
      endpoint.searchParams.set("path", args.pagePath);
      endpoint.searchParams.set("api-version", "7.1");
      endpoint.searchParams.set("versionDescriptor.versionType", "branch");
      endpoint.searchParams.set("versionDescriptor.version", branch);
      const pageResponse = await request(endpoint, { redirect: "error", signal: AbortSignal.timeout(30000), headers: {
        Authorization: `Bearer ${await tokenProvider()}`, "User-Agent": userAgentProvider(), Accept: "application/json",
      } });
      if (!pageResponse.ok) return receipt("INCOMPLETE", { reason: "Published wiki page could not be verified", httpStatus: pageResponse.status }, true);
      const page = await pageResponse.json();
      if (page.path !== args.pagePath || !Number.isInteger(page.id) || page.id <= 0) {
        return receipt("INCOMPLETE", { reason: "Published wiki page identity is incomplete" }, true);
      }
      const pageUrl = `${origin}/${encodeURIComponent(scope.project)}/_wiki/wikis/${encodeURIComponent(wiki.id)}/${page.id}`;
      const uri = `vstfs:///Wiki/WikiPage/${encodeURIComponent(project.id)}%2F${encodeURIComponent(wiki.id)}%2F${args.pagePath.slice(1).split("/").map(encodeURIComponent).join("%2F")}`;
      const tracking = await connection.getWorkItemTrackingApi();
      const readItem = () => tracking.getWorkItem(args.workItemId, undefined, undefined, 1, scope.project);
      const validItem = item => item?.id === args.workItemId && Number.isInteger(item.rev) && item.rev > 0 &&
        item.fields?.["System.TeamProject"] === scope.project && (item.relations === undefined || Array.isArray(item.relations));
      const linked = item => (item.relations ?? []).some(relation =>
        (relation.rel === "ArtifactLink" && typeof relation.url === "string" && sameArtifact(relation.url, uri)) ||
        (relation.rel === "Hyperlink" && samePageHyperlink(relation.url, scope, project, wiki, page, args.wikiIdentifier, branch)));
      const item = await readItem();
      if (!validItem(item)) return receipt("INCOMPLETE", { reason: "Work Item scope or relations unavailable" }, true);
      if (linked(item)) return receipt("UNCHANGED", { workItemId: args.workItemId, pageUrl });
      if (JSON.stringify(scopeReader()) !== JSON.stringify(scope)) return receipt("BLOCKED", { reason: "ADO scope changed" }, true);
      // The revision stays inside the connector. The test makes concurrent relation
      // additions a conflict, so a retry must re-read and detect an existing link.
      writeAttempted = true;
      await tracking.updateWorkItem({}, [
        { op: "test", path: "/rev", value: item.rev },
        { op: "add", path: "/relations/-", value: { rel: "ArtifactLink", url: uri, attributes: { name: "Wiki Page" } } },
      ], args.workItemId, scope.project);
      const verified = await readItem();
      if (!validItem(verified) || !linked(verified)) return receipt("UNVERIFIED", { workItemId: args.workItemId, pageUrl, reason: "Relation write was not confirmed; read before retry" }, true);
      return receipt("LINKED", { workItemId: args.workItemId, pageUrl });
    } catch {
      // Do not print SDK errors: they may contain credentials or remote payloads.
      return receipt(writeAttempted ? "UNVERIFIED" : "INCOMPLETE", {
        reason: writeAttempted ? "Relation may have changed; read Work Item relations before retry" : "Wiki link input, scope, or live reads unavailable",
      }, true);
    }
  };
}

export function configureWorkItemTools(server, tokenProvider, connectionProvider, userAgentProvider) {
  const wrapper = Object.create(server);
  wrapper.tool = (name, description, schema, callback) => name === "wit_add_artifact_link"
    ? server.tool(name, "Link a verified wiki page to its delivery Work Item, without duplicate relations.", linkSchema,
      createWikiLinkHandler(tokenProvider, connectionProvider, userAgentProvider))
    : server.tool(name, description, schema, callback);
  configureVendorTools(wrapper, tokenProvider, connectionProvider, userAgentProvider);
}
