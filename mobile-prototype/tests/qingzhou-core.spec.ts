import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
});

test("规划、深度思考、交付与本地编辑可以连续走通", async ({ page }) => {
  await page.getByRole("button", { name: /8 月去滇西北一周/ }).click();
  await expect(page.getByText("再确认两件事")).toBeVisible();
  await page.getByRole("button", { name: "确认并继续" }).click();
  await expect(page.getByText("规划摘要")).toBeVisible();

  await page.getByRole("button", { name: "开始规划" }).click();
  await expect(page.getByRole("button", { name: /正在深度思考/ })).toBeVisible();
  await page.getByRole("button", { name: /正在深度思考/ }).click();
  await expect(page.getByText("理解需求并融合旅行画像")).toBeHidden();
  await page.getByRole("button", { name: /正在深度思考/ }).click();
  await expect(page.getByText("理解需求并融合旅行画像")).toBeVisible();

  await expect(page.getByRole("button", { name: /深度思考完成/ })).toBeVisible({ timeout: 12_000 });
  await expect(page.getByText("理解需求并融合旅行画像")).toBeHidden();
  await page.getByRole("button", { name: /深度思考完成/ }).click();
  await expect(page.getByText("补充餐饮、天气与游玩提示")).toBeVisible();

  await page.getByRole("button", { name: "查看完整行程" }).click();
  await expect(page.getByRole("heading", { name: "初抵大理，古城慢步" })).toBeVisible();
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByRole("button", { name: "删除" }).last().click();
  await page.getByRole("button", { name: "撤销" }).click();
  await expect(page.getByTestId("flow-current").getByText("人民路晚餐", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "重做" }).click();
  await expect(page.getByTestId("flow-current").getByText("人民路晚餐", { exact: true })).toBeHidden();
  await page.getByTestId("flow-current").getByRole("button", { name: "添加地点" }).click();
  await page.getByRole("button", { name: /沙溪古镇 沙溪古镇/ }).click();
  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.getByText("大理古城 → 崇圣寺三塔 → 沙溪古镇", { exact: true })).toBeVisible();

  await page.reload();
  await page.getByRole("button", { name: "行程" }).click();
  await page.getByRole("button", { name: /滇西北一周深度漫游/ }).click();
  await expect(page.getByText("大理古城 → 崇圣寺三塔 → 沙溪古镇", { exact: true })).toBeVisible();
});

test("画像记忆可确认、新增，并进入下一次规划摘要", async ({ page }) => {
  await page.getByRole("button", { name: "我的" }).click();
  await page.getByRole("button", { name: "确认记住" }).click();
  await expect(page.getByText("更喜欢有水域或山景的住宿")).toBeVisible();
  await page.getByRole("button", { name: "新增" }).click();
  await page.getByRole("textbox", { name: "内容" }).fill("喜欢清晨出发，避开人流");
  await page.getByRole("button", { name: "保存记忆" }).click();
  await expect(page.getByTestId("mobile-scroll-content").getByText("喜欢清晨出发，避开人流", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "规划" }).click();
  await page.getByRole("button", { name: /8 月去滇西北一周/ }).click();
  await page.getByRole("button", { name: "确认并继续" }).click();
  await expect(page.getByText("已参考你的画像")).toBeVisible();
  await expect(page.getByText(/喜欢自然风光和有生活感的古城街巷/)).toBeVisible();
});

test("完整行程以全屏地图和可上拉底板呈现", async ({ page }) => {
  await page.getByRole("button", { name: "行程" }).click();
  await page.getByRole("button", { name: /滇西北一周深度漫游/ }).click();
  await expect(page.getByRole("img", { name: "大理当日路线地图" })).toBeVisible();
  await expect(page.getByRole("button", { name: "上拉展开详情" })).toBeVisible();
  await expect(page.getByRole("button", { name: "继续调整" })).toBeVisible();
  await page.getByRole("button", { name: "推荐地点" }).click();
  await expect(page.getByText("海景咖啡")).toBeHidden();

  await page.getByRole("button", { name: "上拉展开详情" }).click();
  await expect(page.getByRole("button", { name: "下拉收起详情" })).toBeVisible();
  await expect(page.getByText("从南门入城，沿复兴路慢慢走，避开正午的人流。")).toBeVisible();

  await page.getByRole("button", { name: "08.21 周五 Day 2" }).click();
  await expect(page.getByRole("heading", { name: "沿洱海骑行，喜洲田园" })).toBeVisible();
});
