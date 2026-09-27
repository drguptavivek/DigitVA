---
title: WHO ICD-API DORIS and CoDEdit endpoints (reference copy)
doc_type: kb
status: reference
owner: engineering
last_updated: 2026-09-27
---

> Reference copy of WHO's page "DORIS Support (Underlying cause of Death Detection) (ICD-API documentation)" on icd.who.int, saved 2026-09 and
> converted to Markdown. WHO's page is authoritative. Relative links to WHO's other spec pages do not resolve here.

# ICD-API DORIS and CODEDIT Suport

## DORIS Support

DORIS is a multilingual software developed to facilitate the identification of the underlying cause of death. This tool examines the information provided on the death certificates and assists in automatically selecting the underlying cause of death following the mortality rules of the International Classification of Diseases (ICD) that have been fully digitalized.

ICD-API contains full functionality of DORIS for those who want to integrate it into their mortality systems.

We support two ways of calling the DORIS endpoint GET and POST. With GET you can provide information on the death certificate as parameters whereas is POST you can submit a death certificate in the standard format to be processed by the system. Detailed information on how to make calls can be found in [Open API (Swagger) documentation](https://id.who.int/swagger)

In both GET and POST, DORIS responds with an object that contains the processed information.

This object contains the following fields description:

**Underlying cause of death response from DORIS system**

| Name | Description |
|----|----|
| code | Code for computed underlying cause of death. May include postcoordination combinations. |
| stemCode | Stem code for the computed underlying cause of death. |
| uri | URI for the computed underlying cause of death. May include postcoordination combinations. |
| stemURI | Code for the computed underlying cause of death. |
| report | Output report prepared during the computation of the underlying cause of death. |
| tabularReport | Detailed output report in tabular format [(see the format specification)](../DORISTabularOutputSpecs/). |
| reject | Whether the underlying cause of death was rejected due to an error. |
| error | Any errors returned by the doris engine. |
| warning | Any warnings returned by the doris engine. |

## CODEDIT Support

CODEDIT is a system that checks for completeness and inconsistencies in a death certificate and provides you a report based on the analysis.

Similar to DORIS, it supports two ways of calling the endpoint; GET and POST. With GET you can provide information on the death certificate as parameters whereas is POST you can submit a death certificate in the standard format to be processed by the system.

Detailed information on how to make calls can be found in [Open API (Swagger) documentation](https://id.who.int/swagger)

**The output of the checks made are in the following format**

| Name | Description |
|----|----|
| report | output report created after the checks are performed on the death certificate |
| tabularReport | report in tabular format [(see the format specification)](../CODEDITTabularOutputSpecs/). |
| issueIds | list of issue identifiers found in the death certificate [(see the full id list specification)](../DORIS-CODEDIT-IdsListSpecs/). |
