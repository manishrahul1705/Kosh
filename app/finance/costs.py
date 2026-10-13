"""Compare effective annual financing costs using integer-paise inputs."""

from __future__ import annotations

from decimal import Decimal


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
        if npv(mid)>0: lo=mid
        else: hi=mid
    return (lo+hi)/2

def effective_annual_cost(principal_paise:int,repayment_paise:int,days:int)->Decimal:
    return loan_apr(principal_paise,[(days,repayment_paise)])
