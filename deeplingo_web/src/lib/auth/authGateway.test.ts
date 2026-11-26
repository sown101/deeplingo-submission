import { beforeEach, describe, expect, it, vi } from "vitest";
import { createSupabaseGateway } from "./authGateway";
const sdk = vi.hoisted(() => ({
  getSession: vi.fn(), signOut: vi.fn(),
    resetPassword: vi.fn(),
    updatePassword: vi.fn(), unsubscribe: vi.fn(),
  listener: null as ((event:string, session:{user:{id:string};access_token:string}|null) => void) | null,
}));
vi.mock("@supabase/auth-js", () => ({
  GoTrueClient: class {
    getSession = sdk.getSession;
    signOut = sdk.signOut;
    onAuthStateChange(listener: typeof sdk.listener) { sdk.listener = listener; return {data:{subscription:{unsubscribe:sdk.unsubscribe}}}; }
  },
}));
const config = {apiBaseUrl:"/api/v1/v3",supabaseUrl:"https://dummy.supabase.co",supabasePublishableKey:"dummy-public"};

describe("W01 Supabase snapshot boundary", () => {
  beforeEach(() => { vi.clearAllMocks(); sdk.getSession.mockResolvedValue({data:{session:null},error:null}); sdk.signOut.mockResolvedValue({error:null}); });

  it("uses event session directly without reentering getSession and unsubscribes", () => {
    const gateway = createSupabaseGateway(config);
    const callback = vi.fn();
    const unsubscribe = gateway.onAuthStateChange(callback);
    sdk.listener!("SIGNED_IN",{user:{id:"A"},access_token:"dummy-A"});
    expect(callback).toHaveBeenLastCalledWith({userId:"A",accessToken:"dummy-A"},"SIGNED_IN");
    sdk.listener!("SIGNED_OUT",null);
    expect(callback).toHaveBeenLastCalledWith(null,"SIGNED_OUT");
    expect(sdk.getSession).not.toHaveBeenCalled();
    unsubscribe();
    expect(sdk.unsubscribe).toHaveBeenCalledOnce();
  });

  it("propagates safe logout failure instead of claiming logout succeeded", async () => {
    sdk.signOut.mockResolvedValue({error:{message:"private Auth diagnostics"}});
    await expect(createSupabaseGateway(config).signOut()).rejects.toThrow("Sign out could not be confirmed.");
  });

  it("propagates session restoration failure and safely maps a valid restored snapshot", async () => {
    const gateway = createSupabaseGateway(config);
    sdk.getSession.mockResolvedValueOnce({data:{session:null},error:{message:"private diagnostic"}});
    await expect(gateway.currentSession()).rejects.toThrow("Session could not be restored.");
    sdk.getSession.mockResolvedValueOnce({data:{session:{user:{id:"A"},access_token:"dummy-A"}},error:null});
    expect(await gateway.currentSession()).toEqual({userId:"A",accessToken:"dummy-A"});
  });
});
