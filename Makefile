.PHONY: setup test dataset train index demo bundle api ui

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements.txt

test:
	python -m unittest discover -v

dataset:
	python -m src.data.build_dataset --observation-date 2026-08-26

train:
	python -m src.modeling.train

index:
	python -m src.retrieval.comparables

demo:
	python -m src.services.demo

bundle:
	python scripts/manage_demo_artifacts.py build permitpulse-demo-artifacts.tar.gz

api:
	python -m uvicorn src.api.app:app --reload

ui:
	python -m streamlit run ui.py
