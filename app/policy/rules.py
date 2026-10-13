"""Pure policy decisions; this module never executes an action."""
from dataclasses import dataclass,field
from datetime import datetime,timedelta


TIERS={
    "FORECAST":"T0","MATCH":"T0","COMPUTE":"T0",
    "REMINDER_DRAFT":"T1","APPLICATION_PACK_DRAFT":"T1",
    "COLLECTIONS_REMINDER":"T2","SUPPLIER_TERM_REQUEST":"T2",
    "TREDS_FINANCE":"T3","OD_DRAWDOWN":"T3","LOAN_APPLICATION":"T3",
    "SHARE_DATA_PACK":"T3","PAYMENT":"T3","CHANGE_BANK_DETAILS":"T4",
}


@dataclass(frozen=True)
class PolicyContext:
    now:datetime
    global_kill:bool=False
    seller_kill:bool=False
    max_action_paise:int=200_000_000
    max_day_paise:int=1_000_000_000
    day_used_paise:int=0
    allowlist:dict[str,datetime]=field(default_factory=dict)
    actor_role:str|None=None
    approved:bool=False
    otp_verified:bool=False
    consent_valid:bool=False


@dataclass(frozen=True)
class PolicyDecision:
    tier:str
    decision:str
    rule_ids:tuple[str,...]
    reasons:tuple[str,...]

    def as_dict(self):
        return {"tier":self.tier,"decision":self.decision,"rule_ids":list(self.rule_ids),"reasons":list(self.reasons)}


def evaluate(action_type:str,params:dict,context:PolicyContext,*,phase="propose",origin="PLANNER")->PolicyDecision:
    tier=TIERS.get(action_type,"T4");rules=[];reasons=[]
    def deny(rule,reason):rules.append(rule);reasons.append(reason)
    if context.global_kill or context.seller_kill:
        return PolicyDecision("T4","DENY",("KILL_SWITCH",),("The global or seller kill switch is on.",))
    if origin=="DOCUMENT" or params.get("params_origin")=="DOCUMENT":
        return PolicyDecision("T4","DENY",("DOCUMENT_PARAMETERS",),("Document text cannot supply action parameters.",))
    if origin!="PLANNER" and not origin.startswith("ADDON:"):
        deny("TRUSTED_ORIGIN","Only deterministic server planners or registered modules may propose actions.")
    if tier=="T4":deny("FORBIDDEN_ACTION","Unknown actions and bank-detail changes are forbidden.")
    amount=params.get("amount_paise",0)
    if not isinstance(amount,int) or isinstance(amount,bool) or amount<0:
        return PolicyDecision("T4","DENY",("INTEGER_PAISE",),("Amount must be a nonnegative integer number of paise.",))
    if amount>context.max_action_paise:deny("ACTION_LIMIT","Per-action amount limit exceeded.")
    if context.day_used_paise+amount>context.max_day_paise:deny("DAY_LIMIT","Per-day amount limit exceeded.")
    key=params.get("allowlist_key")
    if tier in {"T2","T3"} and not key:deny("ALLOWLIST_REQUIRED","A known counterparty, payee or recipient is required.")
    if key:
        added=context.allowlist.get(key)
        if added is None:deny("ALLOWLIST","Payee, counterparty or recipient is not on the allowlist.")
        elif context.now-added<timedelta(hours=24):deny("COOL_OFF","Newly allowlisted recipients require a 24-hour cool-off.")
    if params.get("sharing_fields") and not context.consent_valid:
        deny("CONSENT_SCOPE","Active consent must cover the purpose, recipient and every shared field.")
    if phase in {"approve","execute"} and tier in {"T2","T3"} and context.actor_role not in {"OWNER","APPROVER"}:
        deny("APPROVER_ROLE","Only OWNER or APPROVER may approve or execute an approved action.")
    if rules:return PolicyDecision("T4" if "ALLOWLIST" in rules and action_type=="PAYMENT" else tier,"DENY",tuple(rules),tuple(reasons))
    if tier in {"T0","T1"}:return PolicyDecision(tier,"ALLOW",("AUTOMATIC_INTERNAL",),("Read/analysis and internal drafts are automatic and audited.",))
    if phase=="execute" and context.approved and (tier!="T3" or context.otp_verified):
        return PolicyDecision(tier,"ALLOW",("APPROVAL_VERIFIED",),("Human approval and required step-up are verified.",))
    required=("HUMAN_APPROVAL","OTP_STEP_UP") if tier=="T3" else ("HUMAN_APPROVAL",)
    return PolicyDecision(tier,"NEEDS_APPROVAL",required,("Human approval is required; money/data actions also require OTP step-up.",))
