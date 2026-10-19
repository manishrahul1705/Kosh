"""Read-only native module catalogue and seller feature settings."""
from app.database.kosh_models import KoshModuleFlag
MODULES={
'collections':('Collections','Drafts, statutory evidence and approved reminders','/operations/collections'),
'sales':('Sales intake','Owner-confirmed expected receivables','/operations/sales'),
'procurement':('Procurement','PO payables, quotes and approved sandbox RFQs','/operations/procurement'),
'pricing':('Pricing','Confirmed purchase cost changes','/operations/pricing'),
'market':('Market intelligence','Offline commodity, power and industry observations','/operations/market'),
'inventory':('Inventory','Stock buffers and financing needs','/operations/inventory'),
'supply_chain':('Supply chain','Documented shipment/payment timing','/operations/supply-chain'),
'customer_intelligence':('Customer intelligence','Optional evidence-based delay enrichment and cash what-if','/operations/customer-intelligence'),
'revenue':('Revenue signal','Optional explainable input; Monte Carlo remains authoritative','/operations/revenue'),
'chat':('Cash chat','Read-only source-linked facts, no action authority','/cash'),
'reports':('Cash reports','One-page pack; scoped T3 sharing','/operations/reports'),
'operations':('Operations / executive review','Deterministic workers and cash-impact timeline','/operations'),
'workflows':('Workflows','Persistent steps pause for human approval','/operations/workflows'),
'notifications':('Notifications','T2 email/WhatsApp-labelled sandbox outbox only','/operations/notifications'),
'onboarding':('Onboarding','Owner-confirmed tracking method, maturity and needs','/operations/onboarding'),
'knowledge':('Knowledge','Inert evidence, SOPs and policies','/operations/knowledge'),
'goals':('Goals and tasks','Evidence-backed cash targets and completion','/operations/goals'),
'tender_to_cash':('Tender to cash','Matched-tender scenario and financing need','/operations/tender-to-cash')}
def enabled(db,seller_id,module):
    row=db.get(KoshModuleFlag,(seller_id,module));return row.enabled if row is not None else True
