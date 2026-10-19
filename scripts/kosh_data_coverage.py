"""Shared route-to-read contract for API tests and fresh-checkout verification."""
CORE = "/api/kosh/sellers/{seller}"
PAGES = [
    ("/", "/api/portal/sellers/{seller}/tenders", "items"),
    ("/ · tender summary", "/api/portal/sellers/{seller}/summary", None),
    ("/tenders/:tenderId", "/api/portal/sellers/{seller}/tenders/{tender}", "documents"),
    ("/profile", "/api/sellers/{seller}", "active_revision.attributes"),
    ("/modules", CORE+"/modules", "items"),
    ("/cash", CORE+"/forecast/latest", "weeks"),
    ("/cash · analysis", CORE+"/analysis", None),
    ("/cash · back-test", CORE+"/forecast/backtest/latest", "windows"),
    ("/cash · proposals", CORE+"/cash-events", "items"),
    ("/cash · chat", CORE+"/chat/history", "items"),
    ("/ledger", CORE+"/ledger", "items"),
    ("/plan", CORE+"/financing/options", "items"),
    ("/plan · allocation", CORE+"/plans/latest", "lines"),
    ("/plan · evidence", CORE+"/financing/evidence", "missing_criteria"),
    ("/plan · safety curve", CORE+"/financing/safety-curve", "items"),
    ("/approvals", CORE+"/actions/intents", "items"),
    ("/approvals · outbox", CORE+"/sandbox/outbox", "items"),
    ("/approvals · settlements", CORE+"/sandbox/executions", "items"),
    ("/approvals · verification inbox", CORE+"/sandbox/inbox", "items"),
    ("/approvals · policy", CORE+"/policy", None),
    ("/audit", CORE+"/audit", "items"),
    ("/audit · counters", CORE+"/audit/security-events", "counts"),
    ("/ledger · obligations", CORE+"/obligations", None),
    ("/connect", CORE+"/documents", None),
    ("/connect · consent", CORE+"/consents", None),
    ("/operations/collections", CORE+"/collections", "items"),
    ("/operations/customer-intelligence", CORE+"/intelligence", "history"),
    ("/operations/revenue", CORE+"/revenue", "weeks"),
    ("/operations/revenue · history", CORE+"/revenue", "history"),
    ("/operations/reports", CORE+"/reports", "items"),
    ("/operations/reports · sharing", CORE+"/consents/sharing", "items"),
    ("/operations/tender-to-cash", CORE+"/tender-to-cash", "items"),
    ("/operations/tender-to-cash/:tenderId", CORE+"/tender-to-cash", "items"),
    ("/operations · dashboard", CORE+"/operations/dashboard", "inventory"),
    ("/operations/notifications · transport", CORE+"/operations/messaging-status", None),
    ("/operations/knowledge · search", CORE+"/operations/knowledge/search?q=finance", "items"),
]
for module in ["", "resources", "sales", "procurement", "pricing", "market", "inventory", "supply-chain", "workflows", "notifications", "onboarding", "knowledge", "goals"]:
    PAGES.append(("/operations"+("/"+module if module else ""), CORE+"/operations", "items"))


def check_pages(get, seller):
    tenders=get(f"/api/portal/sellers/{seller}/tenders")
    assert tenders["items"], "Tender portal is empty"
    tender=tenders["items"][0]["tender_id"]
    results=[]
    for page,template,key in PAGES:
        path=template.format(seller=seller,tender=tender)
        data=get(path)
        selected=data
        if key:
            for part in key.split("."):
                assert part in selected, (page,path,key)
                selected=selected[part]
        assert selected, (page,path,"No seeded data")
        results.append({"page":page,"api":path,"data":key or "response","seeded":"yes"})
    return results
