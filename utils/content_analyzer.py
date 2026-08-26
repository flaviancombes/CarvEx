"""
CarvEx
Content Analyzer
"""

from pathlib import Path


class ContentAnalyzer:

    @staticmethod
    def analyze(path: Path):

        try:

            with open(path, "rb") as f:
                data = f.read(8192)

        except Exception:

            return None

        # ---------- PYTHON ----------

        if b"import " in data or b"def " in data or b"class " in data or data.startswith(b"#!/usr/bin/env python"):

            return ("text/x-python", ".py")

        # ---------- JSP ----------

        if b"<%@ page" in data or b"<jsp:" in data:

            return ("application/jsp", ".jsp")

        # ---------- PHP ----------

        if b"<?php" in data:

            return ("application/x-httpd-php", ".php")

        # ---------- HTML ----------

        if b"<html" in data or b"<!DOCTYPE html" in data:

            return ("text/html", ".html")

        # ---------- XML ----------

        if data.startswith(b"<?xml"):

            return ("application/xml", ".xml")

        # ---------- JSON ----------

        stripped = data.strip()

        if stripped.startswith(b"{") or stripped.startswith(b"["):

            return ("application/json", ".json")

        return None
