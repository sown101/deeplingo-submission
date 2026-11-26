import { expect, test, type Page, type Route } from "@playwright/test";

// Real browser/client wiring; all server/Auth responses are synthetic. No live accounts.
const ITEM = "11111111-1111-1111-1111-111111111111";
const VIDEO = "22222222-2222-2222-2222-222222222222";
const CONCEPT = "66666666-6666-6666-6666-666666666666";
const LO = "55555555-5555-5555-5555-555555555555";
const API = "/api/v1/v3";

function json(route: Route, value: unknown, status = 200) {
  return route.fulfill({status,contentType:"application/json",body:JSON.stringify(value)});
}
async function fixture(page: Page, incompleteB = false) {
  const calls: Array<{owner:string;path:string;method:string;body:unknown}> = [];
  let authOwner = "A";
  const user = (owner:string) => ({id:owner === "A" ? "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" : "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",aud:"authenticated",role:"authenticated",email:owner+"@ci.invalid",app_metadata:{},user_metadata:{},created_at:"2026-01-01T00:00:00Z"});
  await page.route("**/*", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (url.origin === "https://ci-dummy.supabase.co") {
      if (url.pathname.endsWith("/token")) {
        const body = req.postDataJSON() as {email?:string};
        authOwner = body.email?.startsWith("B") ? "B" : "A";
        return json(route,{access_token:"dummy-"+authOwner+".header.token",token_type:"bearer",expires_in:3600,refresh_token:"dummy-refresh-"+authOwner,user:user(authOwner)});
      }
      if (url.pathname.endsWith("/logout")) return json(route,{});
      if (url.pathname.endsWith("/user")) return json(route,user(authOwner));
      return json(route,{message:"not mocked"},400);
    }
    if (url.pathname.startsWith(API + "/")) {
      const owner = req.headers().authorization?.includes("dummy-B.") ? "B" : "A";
      const path = url.pathname.slice(API.length);
      const body: unknown = req.postData() ? req.postDataJSON() : undefined;
      calls.push({owner,path,method:req.method(),body});
      const item = {library_item_id:ITEM,video_id:VIDEO,title:owner+" private video",thumbnail_url:null,duration_ms:1000,source:"youtube",processing_status:"ready",learning_status:"ready",learning_object_count:2,learning_prepared_language_code:"vi",language_code:"en",added_at:"2026-01-01T00:00:00Z",failure:null,description:null,transcript_available:true};
      if (path === "/learner/me/language-profile") return json(route,{learning_language:owner==="B"&&incompleteB?null:"en",support_language:owner==="B"&&incompleteB?null:"vi",is_complete:!(owner==="B"&&incompleteB)});
      if (path === "/languages") return json(route,[{code:"en",name_en:"English",name_native:"English",script:"Latin",is_active:true,display_order:1},{code:"vi",name_en:"Vietnamese",name_native:"Vietnamese",script:"Latin",is_active:true,display_order:2}]);
      if (path === "/learner/me/library/videos") return json(route,[item]);
      if (path === "/learner/me/library/videos/"+ITEM) return json(route,item);
      return json(route,{detail:{message:"unmocked route"}},404);
    }
    if (url.origin === "http://localhost:5173") return route.continue();
    return route.abort();
  });
  return { calls };
}
async function login(page: Page, owner: string) {
  await page.getByLabel("Email").fill(owner+"@ci.invalid");
  await page.getByLabel("Password",{exact:true}).fill("synthetic-password");
  await page.getByRole("button",{name:"Sign in",exact:true}).click();
}
const nav = (page:Page, name:string) => page.getByRole("navigation",{name:"Primary"}).getByRole("link",{name,exact:true});
// M1 Q1: web no longer links to video Practice or Progress; in-flight sessions stay reachable by URL.
// Navigate inside the same SPA (no reload), so cache isolation is still what is tested.
const spaGo = (page:Page, path:string) => page.evaluate((p) => {
  window.history.pushState({}, "", p);
  window.dispatchEvent(new PopStateEvent("popstate"));
}, path);

test("W01 same SPA A -> logout -> B isolates dashboard/library/progress/review/practice", async ({page}) => {
  const f = await fixture(page);
  await page.goto("/signin");
  await login(page,"A");
  await expect(page.getByRole("heading",{name:"Home",exact:true})).toBeVisible();
  await expect(nav(page,"Review")).toHaveCount(0); // Review is a study mode inside the notebook (2026-11-05).
  await expect(nav(page,"Notebook")).toHaveAttribute("href","/words/lists");
  await expect(page.getByText(/Practice evidence/)).toHaveCount(0);
  await expect(nav(page,"Progress")).toHaveCount(1);
  await nav(page,"Home").click(); // the Library was folded into Home
  await expect(page.getByRole("link",{name:"A private video",exact:true})).toBeVisible();
  await page.getByRole("link",{name:"A private video",exact:true}).click();
  await expect(page.getByRole("link",{name:"Practice",exact:true})).toHaveCount(0);
  await spaGo(page,"/progress");
  await expect(page.getByRole("heading",{name:"Progress",exact:true})).toBeVisible();
  await expect(page.getByLabel("80 percent")).toHaveCount(0);
  await page.getByRole("link",{name:"DeepLingo",exact:true}).click();
  await page.getByRole("button", { name: "Account menu", exact: true }).click();
  await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("button",{name:"Sign in",exact:true})).toBeVisible();
  await login(page,"B");
  await expect(page.getByRole("heading",{name:"Home",exact:true})).toBeVisible();
  await nav(page,"Home").click(); // the Library was folded into Home
  await expect(page.getByRole("link",{name:"B private video",exact:true})).toBeVisible();
  await expect(page.getByText("A private video")).toHaveCount(0);
  await page.getByRole("link",{name:"DeepLingo",exact:true}).click();
  await nav(page,"Home").click(); // the Library was folded into Home
  await page.getByRole("link",{name:"B private video",exact:true}).click();
  await expect(page.getByRole("link",{name:"Practice",exact:true})).toHaveCount(0);
  await expect(page.getByText("A private",{exact:false})).toHaveCount(0);
  expect(f.calls.filter((c) => c.owner==="B"&&c.path==="/learner/me/language-profile").length).toBeGreaterThan(0);
});

test("W01 B onboarding is rechecked rather than inheriting A's complete profile", async ({page}) => {
  await fixture(page,true);
  await page.goto("/signin");
  await login(page,"A");
  await expect(page.getByRole("heading",{name:"Home",exact:true})).toBeVisible();
  await page.getByRole("button", { name: "Account menu", exact: true }).click();
  await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("button",{name:"Sign in",exact:true})).toBeVisible();
  await login(page,"B");
  await expect(page.getByRole("heading",{name:"Choose your languages"})).toBeVisible();
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByRole("heading",{name:"Home",exact:true})).toHaveCount(0);
});
