# 16 - Dashboard User Guide

Use this guide to choose a dashboard page and interpret its controls and
results. For general instructions about selecting runs, changing global
controls, reading partial results, and exporting the dashboard, see
[30 - Output Visualizer](30-output-visualizer.md).

The visualizer currently registers 27 pages. Page-local controls are
data-driven, so a selector can be absent or have fewer choices when its source
summary is unavailable. Pages that are disabled by default must be enabled in
the dashboard configuration before they appear.

## Page-By-Page Guide

The Group column gives the navigation item that contains the page. Open that
group, then select the page shown in the Page column. A `Standalone` page is a
top-level navigation item and does not belong to a group.

| Group | Page | What it answers | Main interpretation or controls |
|---|---|---|---|
| N/A | Overview | How large is each run, and what is its basic household/person and auto-VMT profile? | Population cards and core distributions. Difference cards use the first run as the base. The underlying population totals count people and households even though the current KPI labels say person-days and HH-days. |
| N/A | Prepared Trip Demo | How can a page aggregate disaggregate prepared trips directly? | Disabled by default and intended as a developer example. It requires prepared trips in live mode and is omitted from standalone HTML export. |
| Daily Travel | Daily Activity Pattern | What daily activity patterns and mandatory/non-mandatory tour frequencies occur by person type? | Select person type. Tour/trip rates are per person-day measures and do not become shares with the global Values control. Distribution axes currently say persons even when the underlying observations are person-days. |
| Daily Travel | Escorted Tours | How much school escorting occurs, who chauffeurs, and what are the tour-leg/stop/distance patterns? | Direction, escort category, student-count, and person-type views depend on available required and optional escort summaries. |
| N/A | Joint Travel | How common are joint-tour patterns, party sizes, compositions, and household participation? | Household size and party size provide different denominators; read each axis and note before comparing percentages. Multi-day inputs can use household-day or person-day observations, although the current chart axes still say households or people. |
| Long-Term Choices | Individual Choices | How do license holding, bicycle comfort, transit-pass ownership, and transit subsidy vary by person type? | Person-type selectors apply to individual features. Each feature can be unavailable independently. |
| Long-Term Choices | Vehicle Ownership and Type | How many vehicles do households own, and what are the modeled age, fuel, and body-type distributions? | Household-size and vehicle-characteristic views use different source tables and populations. Allocated tour vehicle outputs are on Tour Mode, not this page. |
| Long-Term Choices | Mandatory Location Choice | Where are workers and students located, how far do they travel, and how common are work-from-home/telecommute choices? | Geography, location subject, and distance views use home, work, or school roles. “All geographies” and a selected geography can use different display logic. |
| Long-Term Choices | Employment/Enrollment Match By Geography | How closely do modeled workers/students match employment/enrollment targets? | Choose geography and, for school results, student type. Residual is modeled minus target; percent error needs a nonzero target. |
| Skim Summaries | Tour Skims | What are the distributions and statistics of observed or hypothetical tour skim components? | Select skim scenario/family, direction, component, and mode from available data. Prepared tour data adds detailed views in live mode; export remains summary-based. |
| Skim Summaries | Trip Skims | What are the distributions and statistics of observed or hypothetical trip skim components? | Select skim scenario/family, component, and trip mode. Units come from each skim component and are not converted. |
| Tour Summaries | Tour Purpose | What shares or counts of tours occur by category and purpose? | Category and purpose are separate summaries. Percent mode compares distributions within each plotted total. |
| Tour Summaries | Tour Mode | How do tour modes vary by purpose and auto sufficiency, and what vehicle characteristics are allocated to auto tours? | Purpose, auto-sufficiency, occupancy, and vehicle-characteristic controls use distinct summary features. |
| Tour Summaries | Tour Time | When do tours start and end, and how long do they last? | Select tour purpose. Time bins follow prepared/configured time values. |
| Tour Summaries | Tour Distance | What are tour distance distributions and average distances by purpose and home geography? | Purpose and geography controls affect different views. Existing labels assume prepared distance is in miles. |
| Tour Summaries | Tour Stop Frequency | How many outbound, inbound, and total stops occur, and how frequent are at-work subtours? | Select purpose where offered; stop-frequency codes and derived counts are different measures. |
| Tour Summaries | Internal vs. External Tours | How often do non-mandatory tours cross the model boundary, and where are external destinations? | Select home or destination geography from available summary rows. Do not add overlapping geography totals. |
| Tour Summaries | Park-and-Ride Location | How do modeled PNR tour counts compare with lot capacity? | Select geography. Residuals require valid PNR modes, zones, and capacity data; MAZ output can be hidden by dashboard config. |
| Trip Summaries | Trip and Stop Purpose | What trip purposes occur, and what purposes occur at intermediate stops within each tour purpose? | Select tour purpose for the stop view. Trips and stops use different count fields and denominators. |
| Trip Summaries | Trip Mode | How does trip mode vary by tour purpose and tour mode? | Tour-purpose and tour-mode selectors filter the registered three-dimensional summary. |
| Trip Summaries | Trip and Stop Time | When do trips and stops depart? | Select tour purpose. Departure trip count and departure stop count are separate series. |
| Trip Summaries | Trip and Stop Distance | What are direct trip distances and stop out-of-direction distances? | Select tour purpose and distance range where available. The two charts use different prepared distance fields. |
| Trip Summaries | Parking Location | How do trips parked by zone compare with parking capacity? | Disabled by default and requires live prepared `land_use`. Current summary geography is the base parking MAZ/TAZ, not every named aggregation. |
| Validation Summaries | Traffic Validation | How closely do modeled link/count-location/screenline volumes match observations? | Select period and facility type. RMSE, RMSPE, R-squared, scatter, fit, and screenline outputs have distinct valid-data rules. |
| Validation Summaries | Transit Validation | How do boardings and transfer rates vary by operator, technology, and access mode? | Uses supplied validation summary contracts. A missing operator/technology field can remove only the affected feature. |
| Validation Summaries | VMT Validation | How does personal-auto and non-motorized VMT vary by home geography, income, household size, period, and mode? | Many selectors are dependent. Optional outside tables add external, commercial, and bicycle outputs independently. |
| Validation Summaries | Regional Validation | How do modeled district/county commute flows compare with observed matrices? | Disabled by default. Select flow type and metric: modeled, observed, difference, percent difference, or absolute percent difference. Percent difference needs nonzero observed flow. |

For page IDs, default-enabled status, data prerequisites, and extension
contracts, see [31 - Dashboard Page Contract](31-dashboard-pages.md).

## Related Chapters

- [10 - Getting Started](10-getting-started.md)
- [11 - Configuring Your Data](11-configuring-your-data.md)
- [12 - Running Workflows](12-running-workflows.md)
- [30 - Output Visualizer](30-output-visualizer.md)
- [34 - HTML Export](34-html-export.md)
