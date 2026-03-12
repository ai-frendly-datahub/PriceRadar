"""
PriceRadar - 상품 가격 추적 및 분석 시스템

여러 쇼핑몰의 가격 변동과 딜 정보를 수집하고,
지금 사야 할 상품을 레이더 형태로 제공하는 모듈입니다.
"""

__version__ = "0.1.0"
__author__ = "PriceRadar Team"
import importlib

_ = importlib.import_module("radar_core")
_core_version = "radar-core"
