/** Where a signed-in account lands: the standalone home for a standalone account, else the worklist. */
export const homeRoute = (account: { standalone?: boolean } | undefined) => (account?.standalone ? "/standalone" : "/worklist");
