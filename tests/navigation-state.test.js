const test = require("node:test");
const assert = require("node:assert/strict");

require("../frontend/navigation-state.js");

test("restores a protected chat target after authentication", () => {
  const target = NavigationState.chatTarget();
  assert.deepEqual(NavigationState.resolveAfterAuth(target), {
    page: "chat",
  });
});

test("rejects incomplete detail targets and closed authentication state", () => {
  assert.equal(NavigationState.resolveAfterAuth(null), null);
  assert.equal(NavigationState.resolveAfterAuth({ page: "detail" }), null);
  assert.deepEqual(
    NavigationState.resolveAfterAuth(NavigationState.detailTarget("plan-1")),
    { page: "detail", planId: "plan-1" },
  );
});
