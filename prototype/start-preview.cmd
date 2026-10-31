@echo off
title QA Studio - Local Sample
node "%~dp0serve.cjs" --open
if errorlevel 1 pause
