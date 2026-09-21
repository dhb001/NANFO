import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import * as THREE from "three";
import * as catalogue from "./threeCatalogue";

const featureDirectory = path.join(process.cwd(), "src/features/digitalTwin");

describe("production Three catalogue", () => {
  it("registers every scene JSX constructor, preserving the original Three identities", () => {
    const constructors = new Set<string>();
    for (const filename of readdirSync(featureDirectory).filter((name) => name.endsWith(".tsx") && !name.endsWith(".test.tsx"))) {
      const source = ts.createSourceFile(filename, readFileSync(path.join(featureDirectory, filename), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      const visit = (node: ts.Node) => {
        if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
          const tag = node.tagName.getText(source);
          if (/^[a-z]/.test(tag) && tag !== "primitive" && document.createElement(tag) instanceof HTMLUnknownElement) {
            constructors.add(tag[0].toUpperCase() + tag.slice(1));
          }
        }
        ts.forEachChild(node, visit);
      };
      visit(source);
    }
    expect(constructors.size).toBeGreaterThan(0);
    for (const name of constructors) {
      expect(catalogue, `Missing JSX constructor ${name}`).toHaveProperty(name);
      expect(catalogue[name as keyof typeof catalogue]).toBe(THREE[name as keyof typeof THREE]);
    }
  });

  it("limits the vendor import override to Canvas's constructor registration", () => {
    const require = createRequire(import.meta.url);
    const entry = path.join(path.dirname(require.resolve("@react-three/fiber")), "react-three-fiber.esm.js");
    const source = ts.createSourceFile(entry, readFileSync(entry, "utf8"), ts.ScriptTarget.Latest, true);
    const namespaceUses: string[] = [];
    const visit = (node: ts.Node) => {
      if (ts.isIdentifier(node) && node.text === "THREE") namespaceUses.push(node.parent.getText(source));
      ts.forEachChild(node, visit);
    };
    visit(source);
    // A Fiber upgrade adding any non-catalogue usage must revisit the override.
    expect(namespaceUses).toEqual(["* as THREE", "extend(THREE)"]);
  });
});
