# Pre-checked datasets (curl-tested 2026-11-21, no login needed)

| Dataset | URL | Notes |
|---|---|---|
| **CalEnviroScreen 5.0** (tract-level pollution, health, poverty, race) | `https://publish.data.ca.gov/dataset/72b28c84-ceac-4886-9f71-d422470d2223/resource/c4e277e0-cf23-4a8f-b07e-c8544c5d3d2b/download/calenviroscreen50_070126.csv` | 9,106 tracts, 1,764 with `region == "Bay Area"`. Columns: tract, zipcode, county, ACS2024Pop, CIscore, CIscoreP, ozone, pm, diesel, traffic, asthma, lbw, cvd, pov, edu, ling, unemp, housingB, hisp, white, black, asian. The `tract` value is the GEOID. |
| **SF 311** | `https://data.sfgov.org/resource/vw6y-z8j6.csv?$limit=50000` | 9M rows, 2008 to now. Always filter with `$where=requested_datetime > '2025-01-01'`. Columns: requested_datetime, closed_date, service_name, service_subtype, analysis_neighborhood, supervisor_district, lat, long, source. |
| **Oakland 311** | `https://data.oaklandca.gov/resource/quth-gb8e.csv?$limit=50000` | 1.2M rows, 2013 to now. Columns: datetimeinit, datetimeclosed, reqcategory, description, councildistrict, srx (lon), sry (lat), zipcode. Some lat/lon are blank. |
| **EPA daily AQI by county** | `https://aqs.epa.gov/aqsweb/airdata/daily_aqi_by_county_2024.zip` (change the year) | Columns: county Name, Date, AQI, Category, Defining Parameter. Bay Area counties have 319–366 days each. |
| **Zillow ZORI, city** | `https://files.zillowstatic.com/research/public_csvs/zori/City_zori_uc_sfrcondomfr_sm_month.csv` | Wide format (one column per month, 2015-01 to 2026-10); melt it. 75 Bay Area cities. Metro version: `Metro_zori_uc_sfrcondomfr_sm_month.csv`. |
| **HUD Fair Market Rents FY26** | `https://www.huduser.gov/portal/datasets/fmr/fmr2026/FY26_FMRs.xlsx` | Needs a browser User-Agent. `fmr_0` to `fmr_4` are studio to 4 bedroom, by county. |
| **BART hourly origin-destination** | `https://afcweb.bart.gov/ridership/origin-destination/date-hour-soo-dest-2024.csv.gz` (2019 to 2026) | About 33 MB per year, no header row: date, hour, origin, dest, trips. |
| **BART monthly** | `https://www.bart.gov/sites/default/files/2025-02/ridership_2024.zip` | Station-by-station matrices in xlsx with a 4-row title header. |
| **CDE chronic absenteeism 23-24** | `https://www3.cde.ca.gov/demo-downloads/attendance/chronicabsenteeism24.txt` | Tab-separated, 34 MB. Filter `Aggregate Level == "S"` and `Reporting Category == "TA"`, which leaves 10,139 schools. |
| **CA Dashboard absenteeism** | `https://www3.cde.ca.gov/researchfiles/cadashboard/chronicdownload2025.txt` | Tab-separated. Columns: cds, schoolname, districtname, studentgroup, currstatus, priorstatus, change, color. |
| **SF street trees** | `https://data.sfgov.org/resource/tkzw-k3nq.csv?$limit=200000` | 144,650 trees with lat/lon and neighborhood. |
| **Tract median income (ACS)** | `https://P3ePLMYs2RVChkJx.svcs.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/ACS_Median_Household_Income_View_Centroids/FeatureServer/2/query?where=GEOID+LIKE+'06001%25'&outFields=GEOID,NAME,B19049_001E&returnGeometry=false&f=json` | Esri Living Atlas. Page through results with `resultOffset` (max 1000 rows per request). |

**Doesn't work:** api.census.gov now needs a key (free signup). oehha.ca.gov blocks scripts; use the data.ca.gov link above.

## Front-runner ideas
1. **Who breathes the worst air, and who gets their potholes fixed?** Join CalEnviroScreen 5.0 tracts with 311 response times (SF and Oakland). Does the city respond more slowly in the tracts that are already the most burdened? There's a hero chart (response time vs. CES percentile), an address lookup, and a map.
2. **The 311 gap: SF vs. Oakland.** The same request type (illegal dumping, streetlights) compared across the two cities, by neighborhood and income. It includes a "how long would your request take" tool.
3. **Rent clock.** Zillow city rents vs. HUD fair market rent: how many hours of minimum-wage work a month of rent costs, city by city, 2015 to 2026.
