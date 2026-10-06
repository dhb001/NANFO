import { describe, expect, it, vi } from "vitest";
import { PLAN_COLORS, drawPlan, layoutPlan, pickPlanPoint } from "./twinPlan2d";

const nodes = [
  { id: "west", x: -10, z: 0 },
  { id: "east", x: 10, z: 0 },
  { id: "south", x: 0, z: 5 },
];
const links = [
  { sourceId: "west", targetId: "east" },
  { sourceId: "east", targetId: "missing" },
];

describe("twinPlan2d", () => {
  it("fits the plan with one uniform scale, east to the right and south (+z) downwards", () => {
    const layout = layoutPlan(nodes, links, { width: 440, height: 440, padding: 20 });
    const [west, east, south] = layout.points;
    expect(west?.x).toBeCloseTo(20);
    expect(east?.x).toBeCloseTo(420);
    expect(south?.x).toBeCloseTo(220);
    // Uniform scale (400 px / 20 m) and vertical centring of the 5 m tall extent.
    expect((south?.y ?? 0) - (west?.y ?? 0)).toBeCloseTo(100);
    expect(((west?.y ?? 0) + (south?.y ?? 0)) / 2).toBeCloseTo(220);
    expect(layout.shownLinks).toBe(1);
    expect([...layout.segments]).toEqual([west?.x, west?.y, east?.x, east?.y].map((value) => Math.fround(value ?? 0)));
  });

  it("centres a single device and tolerates non-finite coordinates", () => {
    const layout = layoutPlan([{ id: "only", x: Number.NaN, z: 7 }], [], { width: 300, height: 200 });
    expect(layout.points[0]).toMatchObject({ x: 150, y: 100 });
    expect(layoutPlan([], [], { width: 300, height: 200 }).points).toEqual([]);
  });

  it("keeps the selected and alerting devices first when truncating, and reports the truncation", () => {
    const many = Array.from({ length: 10 }, (_, index) => ({ id: `n${index}`, x: index, z: index }));
    const layout = layoutPlan(many, [{ sourceId: "n0", targetId: "n9" }, { sourceId: "n8", targetId: "n9" }], {
      width: 100, height: 100, maxNodes: 3, maxLinks: 1, alertingIds: new Set(["n9"]), selectedId: "n8",
    });
    expect(layout.points.map((point) => point.id)).toEqual(["n8", "n9", "n0"]);
    expect(layout.points.find((point) => point.id === "n9")).toMatchObject({ alert: true, selected: false });
    expect(layout.points.find((point) => point.id === "n8")).toMatchObject({ alert: false, selected: true });
    expect(layout).toMatchObject({ shownNodes: 3, totalNodes: 10, shownLinks: 1, totalLinks: 2 });
  });

  it("picks the nearest device within the radius only", () => {
    const layout = layoutPlan(nodes, links, { width: 440, height: 440, padding: 20 });
    const east = layout.points[1];
    expect(pickPlanPoint(layout, (east?.x ?? 0) + 3, (east?.y ?? 0) - 2)).toBe("east");
    expect(pickPlanPoint(layout, (east?.x ?? 0) + 30, east?.y ?? 0)).toBeNull();
  });

  it("draws devices as circles and alerting devices as distinct larger squares (not colour alone)", () => {
    const layout = layoutPlan(nodes, links, { width: 440, height: 440, alertingIds: new Set(["south"]), selectedId: "east" });
    const fills: string[] = [];
    const context = {
      setTransform: vi.fn(), clearRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(), arc: vi.fn(), fill: vi.fn(), fillRect: vi.fn(),
      lineWidth: 0, strokeStyle: "",
      set fillStyle(value: string) { fills.push(value); },
    };
    drawPlan(context as unknown as CanvasRenderingContext2D, layout, 2);
    const south = layout.points[2];
    expect(context.setTransform).toHaveBeenCalledWith(2, 0, 0, 2, 0, 0);
    expect(context.lineTo).toHaveBeenCalledTimes(1);
    // Two plain devices + one selection ring; the alerting device is a 10 px square.
    expect(context.arc).toHaveBeenCalledTimes(3);
    expect(context.fillRect).toHaveBeenCalledExactlyOnceWith((south?.x ?? 0) - 5, (south?.y ?? 0) - 5, 10, 10);
    expect(fills).toEqual([PLAN_COLORS.device, PLAN_COLORS.alert]);
  });
});
