import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Linking, Platform, Text } from "react-native";

import {
  ContextualHelpBanner,
  SCREEN_HELP_CONFIG,
  clearContextualHelpCache,
  fetchContextualHelp,
  openHelpGuide,
  readExpandedPreference,
  writeExpandedPreference,
  type ContextualHelpScreen,
} from "../src/web/ContextualHelp";

const ALL_SCREENS: readonly ContextualHelpScreen[] = [
  "home",
  "deathRegistration",
  "myRegisteredDeaths",
  "collection",
  "interview",
  "caseDetail",
  "coding",
  "caseCoding",
  "reviewing",
  "caseReviewing",
  "caseView",
  "mentoring",
  "supervision",
  "organization",
  "settings",
];

describe("ContextualHelpBanner", () => {
  let localStorageMock: Record<string, string>;

  beforeEach(() => {
    jest.clearAllMocks();
    clearContextualHelpCache();
    localStorageMock = {};

    const mockStorage = {
      getItem: jest.fn((key: string) => localStorageMock[key] ?? null),
      setItem: jest.fn((key: string, value: string) => {
        localStorageMock[key] = String(value);
      }),
      removeItem: jest.fn((key: string) => {
        delete localStorageMock[key];
      }),
      clear: jest.fn(() => {
        localStorageMock = {};
      }),
    };

    Object.defineProperty(globalThis, "window", {
      value: {
        localStorage: mockStorage,
        open: jest.fn(),
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe("SCREEN_HELP_CONFIG completeness", () => {
    it.each(ALL_SCREENS)("defines valid help config for screen: %s", (screen) => {
      const config = SCREEN_HELP_CONFIG[screen];
      expect(config).toBeDefined();
      expect(typeof config.stageBadge).toBe("string");
      expect(config.stageBadge.length).toBeGreaterThan(5);
      expect(typeof config.title).toBe("string");
      expect(config.title.length).toBeGreaterThan(5);
      expect(typeof config.summary).toBe("string");
      expect(config.summary.length).toBeGreaterThan(10);
      expect(Array.isArray(config.bullets)).toBe(true);
      expect(config.bullets.length).toBeGreaterThanOrEqual(3);
      expect(config.bullets.length).toBeLessThanOrEqual(5);
      expect(Array.isArray(config.sections)).toBe(true);
      expect(config.sections.length).toBeGreaterThanOrEqual(1);
      for (const sec of config.sections) {
        expect(typeof sec.heading).toBe("string");
        expect(sec.heading.length).toBeGreaterThan(3);
        expect(sec.items.length).toBeGreaterThanOrEqual(1);
      }
      expect(config.helpSlug.startsWith("/help/")).toBe(true);
      expect(typeof config.helpLabel).toBe("string");
    });

    it("maps all 15 screens to their expected /help/... guide slugs", () => {
      expect(SCREEN_HELP_CONFIG.home.helpSlug).toBe("/help/getting-started");
      expect(SCREEN_HELP_CONFIG.deathRegistration.helpSlug).toBe("/help/data-collection");
      expect(SCREEN_HELP_CONFIG.myRegisteredDeaths.helpSlug).toBe("/help/data-collection");
      expect(SCREEN_HELP_CONFIG.collection.helpSlug).toBe("/help/data-collection");
      expect(SCREEN_HELP_CONFIG.interview.helpSlug).toBe("/help/data-collection");
      expect(SCREEN_HELP_CONFIG.caseDetail.helpSlug).toBe("/help/data-collection");
      expect(SCREEN_HELP_CONFIG.coding.helpSlug).toBe("/help/coding-workflow");
      expect(SCREEN_HELP_CONFIG.caseCoding.helpSlug).toBe("/help/coding-workflow");
      expect(SCREEN_HELP_CONFIG.reviewing.helpSlug).toBe("/help/coding-workflow");
      expect(SCREEN_HELP_CONFIG.caseReviewing.helpSlug).toBe("/help/coding-workflow");
      expect(SCREEN_HELP_CONFIG.caseView.helpSlug).toBe("/help/viewing-history");
      expect(SCREEN_HELP_CONFIG.mentoring.helpSlug).toBe("/help/mentoring-institutes");
      expect(SCREEN_HELP_CONFIG.supervision.helpSlug).toBe("/help/user-roles");
      expect(SCREEN_HELP_CONFIG.organization.helpSlug).toBe("/help/user-roles");
      expect(SCREEN_HELP_CONFIG.settings.helpSlug).toBe("/help/getting-started");
    });
  });

  describe("Rendering and expand/collapse behavior", () => {
    it.each(ALL_SCREENS)("renders collapsed banner by default for screen: %s", (screen) => {
      let tree!: ReactTestRenderer;
      act(() => {
        tree = create(<ContextualHelpBanner screen={screen} />);
      });

      const config = SCREEN_HELP_CONFIG[screen];
      const root = tree.root;

      // Summary text is rendered
      const allText = root.findAllByType(Text).map((t) => t.props.children).flat();
      expect(allText).toContain(config.summary);

      // Toggle button is in collapsed state
      const toggle = root.find(
        (node) =>
          node.props?.accessibilityRole === "button" &&
          node.props?.accessibilityLabel === "How this screen works"
      );
      expect(toggle).toBeDefined();
      expect(toggle.props.accessibilityState).toEqual({ expanded: false });

      // Bullets are NOT rendered
      for (const bullet of config.bullets) {
        expect(allText).not.toContain(bullet);
      }

      // Help link button is present
      const guideLink = root.find(
        (node) =>
          node.props?.accessibilityRole === "link" &&
          node.props?.accessibilityLabel === `Open ${config.helpLabel}`
      );
      expect(guideLink).toBeDefined();
    });

    it("toggles expanded state, renders stage badge & structured sections, and updates localStorage on press", () => {
      let tree!: ReactTestRenderer;
      act(() => {
        tree = create(<ContextualHelpBanner screen="coding" />);
      });

      const config = SCREEN_HELP_CONFIG.coding;

      // Initially collapsed
      expect(localStorageMock["digitva.helpExpanded.coding"]).toBeUndefined();

      const getToggle = () =>
        tree.root.find((node) => node.props?.accessibilityRole === "button");

      // Expand
      act(() => {
        getToggle().props.onPress();
      });

      expect(getToggle().props.accessibilityLabel).toBe("Hide guide");
      expect(getToggle().props.accessibilityState).toEqual({ expanded: true });
      expect(localStorageMock["digitva.helpExpanded.coding"]).toBe("true");

      // Verify title, stageBadge, bullets, and section headings/items are now displayed
      const expandedText = tree.root.findAllByType(Text).map((t) => t.props.children).flat();
      expect(expandedText).toContain(config.title);
      expect(expandedText).toContain(config.stageBadge);
      for (const bullet of config.bullets) {
        expect(expandedText).toContain(bullet);
      }
      for (const sec of config.sections) {
        expect(expandedText).toContain(sec.heading);
        for (const item of sec.items) {
          expect(expandedText).toContain(item);
        }
      }

      // Collapse
      act(() => {
        getToggle().props.onPress();
      });

      expect(getToggle().props.accessibilityLabel).toBe("How this screen works");
      expect(getToggle().props.accessibilityState).toEqual({ expanded: false });
      expect(localStorageMock["digitva.helpExpanded.coding"]).toBe("false");
    });

    it("starts closed on mount even when localStorage has a prior value, and closes via backdrop or close button", () => {
      localStorageMock["digitva.helpExpanded.mentoring"] = "true";

      let tree!: ReactTestRenderer;
      act(() => {
        tree = create(<ContextualHelpBanner screen="mentoring" />);
      });

      const config = SCREEN_HELP_CONFIG.mentoring;
      const initialText = tree.root.findAllByType(Text).map((t) => t.props.children).flat();

      // Flyout starts closed so it never covers the screen on mount
      for (const bullet of config.bullets) {
        expect(initialText).not.toContain(bullet);
      }

      const toggle = tree.root.find((node) => node.props?.accessibilityRole === "button");
      expect(toggle.props.accessibilityState).toEqual({ expanded: false });

      // Open flyout
      act(() => {
        toggle.props.onPress();
      });
      expect(
        tree.root.find((node) => node.props?.testID === "contextual-help-flyout-mentoring")
      ).toBeDefined();

      // Close via backdrop press
      const backdrop = tree.root.find(
        (node) => node.props?.testID === "contextual-help-backdrop-mentoring"
      );
      act(() => {
        backdrop.props.onPress();
      });
      expect(
        tree.root.findAll((node) => node.props?.testID === "contextual-help-flyout-mentoring")
      ).toHaveLength(0);
    });
  });

  describe("Dedicated Contextual Help API client (fetchContextualHelp)", () => {
    it("fetches and normalizes snake_case payload from /api/v1/help/contextual/<screen> and caches it", async () => {
      const fetchMock = jest.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          page_key: "interview",
          stage_badge: "Stage 2 of 5 · Family Interview",
          title: "Server WHO VA Questionnaire",
          summary: "Server-provided interview help summary.",
          bullets: ["Bullet A", "Bullet B", "Bullet C"],
          sections: [
            {
              heading: "Server Section Heading",
              items: ["Server section item 1"],
            },
          ],
          help_slug: "/help/data-collection",
          help_label: "Data Collection Guide",
        }),
      });
      Object.defineProperty(globalThis, "fetch", {
        value: fetchMock,
        writable: true,
        configurable: true,
      });

      const first = await fetchContextualHelp("interview");
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(fetchMock).toHaveBeenCalledWith("/api/v1/help/contextual/interview", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      expect(first).toEqual({
        stageBadge: "Stage 2 of 5 · Family Interview",
        title: "Server WHO VA Questionnaire",
        summary: "Server-provided interview help summary.",
        bullets: ["Bullet A", "Bullet B", "Bullet C"],
        sections: [
          {
            heading: "Server Section Heading",
            items: ["Server section item 1"],
          },
        ],
        helpSlug: "/help/data-collection",
        helpLabel: "Data Collection Guide",
      });

      // Second call uses in-memory cache without re-fetching
      const second = await fetchContextualHelp("interview");
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(second).toEqual(first);
    });

    it("returns null gracefully when fetch fails or returns non-OK", async () => {
      Object.defineProperty(globalThis, "fetch", {
        value: jest.fn().mockResolvedValue({ ok: false, status: 404 }),
        writable: true,
        configurable: true,
      });
      expect(await fetchContextualHelp("coding")).toBeNull();

      Object.defineProperty(globalThis, "fetch", {
        value: jest.fn().mockRejectedValue(new Error("Network offline")),
        writable: true,
        configurable: true,
      });
      expect(await fetchContextualHelp("reviewing")).toBeNull();
    });
  });

  describe("Opening help guides", () => {
    it.each(ALL_SCREENS)("opens corresponding help guide URL for screen: %s", (screen) => {
      const config = SCREEN_HELP_CONFIG[screen];
      const windowOpenSpy = jest.fn();
      (window as unknown as { open: jest.Mock }).open = windowOpenSpy;

      let tree!: ReactTestRenderer;
      act(() => {
        tree = create(<ContextualHelpBanner screen={screen} />);
      });

      const guideLink = tree.root.find((node) => node.props?.accessibilityRole === "link");
      act(() => {
        guideLink.props.onPress();
      });

      if (Platform.OS === "web") {
        expect(windowOpenSpy).toHaveBeenCalledWith(config.helpSlug, "_blank");
      }
    });

    it("falls back to Linking.openURL when window.open is unavailable", () => {
      const linkingSpy = jest.spyOn(Linking, "openURL").mockResolvedValue(true);
      Object.defineProperty(globalThis, "window", {
        value: undefined,
        writable: true,
        configurable: true,
      });

      openHelpGuide("/help/coding-workflow");
      expect(linkingSpy).toHaveBeenCalledWith("/help/coding-workflow");
    });
  });

  describe("Storage preference helpers", () => {
    it("safely handles missing window or localStorage in read/write", () => {
      Object.defineProperty(globalThis, "window", {
        value: undefined,
        writable: true,
        configurable: true,
      });

      expect(readExpandedPreference("home")).toBe(false);
      expect(() => writeExpandedPreference("home", true)).not.toThrow();
    });

    it("handles throwing storage gracefully", () => {
      Object.defineProperty(globalThis, "window", {
        value: {
          localStorage: {
            getItem: () => {
              throw new Error("SecurityError: localStorage is disabled");
            },
            setItem: () => {
              throw new Error("SecurityError: localStorage is disabled");
            },
          },
        },
        writable: true,
        configurable: true,
      });

      expect(readExpandedPreference("home")).toBe(false);
      expect(() => writeExpandedPreference("home", true)).not.toThrow();
    });
  });
});
