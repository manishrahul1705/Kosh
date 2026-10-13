"""Compare effective annual financing costs using integer-paise inputs."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def discounting_effective_rate(amount_paise:int, discount_paise:int, fee_paise:int, days:int)->Decimal:
    if amount_paise<=discount_paise+fee_paise or days<=0: raise ValueError("invalid financing cash flows")
    return (Decimal(discount_paise+fee_paise)/Decimal(amount_paise-discount_paise-fee_paise))*Decimal(365)/Decimal(days)

def loan_apr(principal_paise:int, repayments:list[tuple[int,int]], fee_paise:int=0)->Decimal:
    """Annualized IRR using Decimal bisection over dated borrower cash flows."""
    net=Decimal(principal_paise-fee_paise)
    if net<=0 or not repayments: raise ValueError("invalid financing cash flows")
    lo,hi=Decimal("-0.999999"),Decimal("10")
    def npv(rate): return net-sum(Decimal(v)/((Decimal(1)+rate)**(Decimal(d)/Decimal(365))) for d,v in repayments)
    for _ in range(160):
        mid=(lo+hi)/2
        if npv(mid)>0: hi=mid
        else: lo=mid
    return (lo+hi)/2

def effective_annual_cost(principal_paise:int,repayment_paise:int,days:int)->Decimal:
    return loan_apr(principal_paise,[(days,repayment_paise)])


def financing_quote(product:dict, amount_paise:int,*,days:int|None=None)->dict:
    """Dated illustrative cash flows; never treat nominal interest as effective cost."""
    model=product["cost_model"];days=int(model["tenor_days"] if days is None else days)
    if days<=0:raise ValueError("Financing tenor must be positive")
    if amount_paise<=0:
        return {"amount_paise":amount_paise,"days":days,"cost_paise":0,"net_proceeds_paise":0,"effective_annual_rate":"0"}
    relationship=product["id"] in {"COLLECTIONS_PUSH","SUPPLIER_TERM_EXTENSION"}
    def money(value):return int(value.quantize(Decimal("1"),rounding=ROUND_HALF_UP))
    interest=0 if relationship else money(Decimal(amount_paise)*Decimal(model["annual_rate"])*Decimal(days)/365)
    fee=0 if relationship else money(Decimal(amount_paise)*Decimal(model.get("processing_fee_rate","0")))
    cost=interest+fee
    if relationship:rate=Decimal(0);net=amount_paise
    elif product["id"]=="TREDS_INVOICE_DISCOUNTING":
        rate=discounting_effective_rate(amount_paise,interest,fee,days);net=amount_paise-cost
    else:
        rate=loan_apr(amount_paise,[(days,amount_paise+interest)],fee);net=amount_paise-fee
    return {"amount_paise":amount_paise,"days":days,"cost_paise":cost,"net_proceeds_paise":net,"effective_annual_rate":str(rate)}
