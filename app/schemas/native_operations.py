"""Typed operational facts; never accept arbitrary action bodies."""
from datetime import date
from decimal import Decimal
from typing import Literal,Annotated,Union
from pydantic import BaseModel,ConfigDict,Field,StrictInt
class Evidence(BaseModel):
    model_config=ConfigDict(extra="forbid")
    evidence_ref:str=Field(min_length=1,max_length=160)
class MaterialIn(Evidence):
    kind:Literal['MATERIAL']
    material_code:str=Field(pattern=r'^[A-Z0-9_-]{1,40}$')
    quantity:StrictInt=Field(ge=0,le=1000000)
    reorder_point:StrictInt=Field(ge=0,le=1000000)
    unit_cost_paise:StrictInt=Field(ge=0,le=9000000000)
    quantity_unit:Literal['UNIT','KG','KWH']='UNIT'
    supplier_id:StrictInt|None=None
class InventoryIn(Evidence):
    kind:Literal['INVENTORY']
    material_id:StrictInt=Field(gt=0)
    quantity:StrictInt=Field(ge=0,le=1000000)
class QuoteIn(Evidence):
    kind:Literal['QUOTE']
    rfq_draft_id:StrictInt=Field(gt=0)
    supplier_id:StrictInt=Field(gt=0)
    price_paise:StrictInt=Field(gt=0,le=9000000000000000)
    lead_days:StrictInt|None=Field(default=None,ge=0,le=730)
    quality_score:Decimal|None=Field(default=None,ge=0,le=1)
    reliability_score:Decimal|None=Field(default=None,ge=0,le=1)
class ShipmentIn(Evidence):
    kind:Literal['SHIPMENT']
    purchase_order_id:StrictInt=Field(gt=0)
    expected_date:date
class ShipmentStepIn(Evidence):
    kind:Literal['SHIPMENT_STEP']
    shipment_id:StrictInt=Field(gt=0)
    milestone:Literal['DISPATCHED','AT_HUB','DELIVERED','DELAYED']
    observed_date:date
    documented_payment_date:date|None=None
class GoalIn(Evidence):
    kind:Literal['GOAL']
    goal:Literal['CASH_BUFFER','COLLECTIONS','MARGIN']
    target_paise:StrictInt=Field(ge=0,le=9000000000000000)
    due_date:date
class TaskIn(Evidence):
    kind:Literal['TASK']
    goal_id:StrictInt=Field(gt=0)
    assigned_role:Literal['OWNER','OPERATIONS','FINANCE']
    due_date:date
class KnowledgeIn(Evidence):
    kind:Literal['KNOWLEDGE']
    topic:Literal['PAYMENT_TERMS','PURCHASE_COST','MATERIAL_PRICE','GENERAL','SOP','PRICING_RULE','SUPPLIER_POLICY','MANUFACTURING_PROCEDURE']
    title:str|None=Field(default=None,max_length=160)
    tags:list[str]=Field(default_factory=list,max_length=10)
    text:str=Field(min_length=1,max_length=4000)
class OnboardingIn(Evidence):
    kind:Literal['ONBOARDING']
    tracking_method:Literal['NOTEBOOK','SPREADSHEET','ERP']
    maturity:Literal['BEGINNER','GROWING','ADVANCED']
    needs: list[Literal['COLLECTIONS','INVENTORY','PRICING','SALES','REPORTS']]=Field(min_length=1,max_length=5)
class MarketIn(Evidence):
    kind:Literal['MARKET_SIGNAL']
    material_code:str=Field(pattern=r'^[A-Z0-9_-]{1,40}$')
    category:Literal['COMMODITY','POWER_TARIFF','INDUSTRY_NEWS']
    change_percent:Decimal=Field(ge=-100,le=100)
    observed_date:date
    headline:str=Field(min_length=1,max_length=500)
class RiskIn(Evidence):
    kind:Literal['STRUCTURAL_RISK']
    material_id:StrictInt=Field(gt=0)
    risk:Literal['SINGLE_SUPPLIER','PRICE_VOLATILITY','STOCKOUT']
    observation:str=Field(min_length=1,max_length=1000)
ResourceIn=Annotated[Union[MaterialIn,InventoryIn,QuoteIn,ShipmentIn,ShipmentStepIn,GoalIn,TaskIn,KnowledgeIn,OnboardingIn,MarketIn,RiskIn],Field(discriminator='kind')]
class WorkflowIn(Evidence):draft_id:StrictInt=Field(gt=0)
class NotificationIn(Evidence):
    channel:Literal['EMAIL','WHATSAPP']='EMAIL'
    record_id:StrictInt=Field(gt=0)
    counterparty_id:StrictInt=Field(gt=0)
class AgentIn(Evidence):agent:Literal['executive','collections','sales','procurement','supplier','pricing','market','customer','revenue','reporting']
class CompletionIn(Evidence):pass
class MaterialCSVIn(Evidence):csv_text:str=Field(min_length=1,max_length=64000)

class CounterpartyIn(Evidence):
    name:str=Field(min_length=1,max_length=255)
    kind:Literal['CUSTOMER','SUPPLIER']
    contact_label:str|None=Field(default=None,max_length=160)
class ConversationIn(Evidence):
    counterparty_id:StrictInt=Field(gt=0)
    channel:Literal['WEB','EMAIL','WHATSAPP']
    text:str=Field(min_length=1,max_length=2000)

class SurchargeIn(Evidence):
    sales_order_id:StrictInt=Field(gt=0)
    cost_change_percent:Decimal=Field(ge=-100,le=100)
