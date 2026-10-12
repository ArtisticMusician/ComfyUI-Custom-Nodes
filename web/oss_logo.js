/**
 * StemSplitter - brand badge on the nodes.
 *
 * Placement: the bottom-right corner of the node itself.
 *
 * How it attaches, and why: with ComfyUI's new node rendering a node is a DOM element
 * (`div.lg-node[data-node-id]`, absolutely positioned), so node painting hooks such as
 * onDrawForeground are never called and anything drawn there never appears. A DOM widget
 * does render, so one is added purely as a mount point inside the node's DOM; from it the
 * node's own element is found and the badge is anchored to that element's corner. A
 * widget occupies a row, which is why the badge is not itself the widget.
 *
 * Which nodes it applies to: every node in this pack. They are matched by the pack's menu
 * namespace, "One Solo Studios", so a node added later is covered without touching this
 * file.
 */
import { app } from "../../scripts/app.js";

// Every node in the pack, matched by the pack's own menu namespace rather than by a list
// of class names, so a node added later cannot be missed. The class names are collected as
// ComfyUI registers them, which is what lets setup() below cover nodes already on canvas.
const BRAND = "One Solo Studios";
const PACK_NODES = new Set();

// Derived from this file's own location: it sits next to the SVG, so the URL is correct
// whatever base path ComfyUI is served under. api.apiURL() gave the browser a URL it
// could not load, which showed as a broken image.
const LOGO_URL = new URL("oss_logo.svg", import.meta.url).href;
const SIZE = 24; // the artwork's native size: viewBox is 0 0 24 24, so this is 1:1
const INSET = 6; // distance from the node's bottom and right edges

const BADGE_SELECTOR = ":scope > img.oss-badge";

function makeBadge() {
    const img = document.createElement("img");
    img.className = "oss-badge";
    img.src = LOGO_URL;
    img.alt = "OSS"; // shows in place of the mark if the file ever fails to load
    img.title = "One Solo Studios";
    img.style.cssText =
        `position:absolute;right:${INSET}px;bottom:${INSET}px;` +
        `width:${SIZE}px;height:${SIZE}px;pointer-events:none;`;
    return img;
}

function placeIn(root) {
    if (!root || root.querySelector(BADGE_SELECTOR)) return false;
    root.appendChild(makeBadge());
    return true;
}

app.registerExtension({
    name: "StemSplitter.Badge",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!(nodeData?.category ?? "").startsWith(BRAND)) return;
        PACK_NODES.add(nodeType.ComfyClass ?? nodeData.name);

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            if (this.stemSplitterBadge) return;
            this.stemSplitterBadge = true;

            // A DOM widget is the reliable way to get an element inside the node's own DOM.
            // It is only a mount point - the badge below is anchored to the node element.
            const mount = document.createElement("div");
            mount.style.display = "none";
            const slot = this.addDOMWidget("oss_logo", "logo", mount, { serialize: false });
            slot.computeSize = () => [0, 0]; // takes no room: not a row

            const place = () => placeIn(slot.element?.closest?.("[data-node-id]"));

            // The node's DOM does not exist the instant it is created, so retry briefly
            // rather than assuming it is there.
            const tryPlace = (tries) => {
                if (!place() && tries > 0) requestAnimationFrame(() => tryPlace(tries - 1));
            };
            requestAnimationFrame(() => tryPlace(30));
        };
    },

    async setup() {
        // Nodes already on the canvas when this extension loads never saw onNodeCreated,
        // so look their element up by id. The frontend identifies a node the same way.
        for (const node of app.graph?._nodes ?? []) {
            if (!PACK_NODES.has(node.type)) continue;
            placeIn(document.querySelector(`[data-node-id="${node.id}"]`));
        }
    },
});
