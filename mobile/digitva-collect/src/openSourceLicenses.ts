/** Full MIT notices bundled with the phone app so the notices remain readable offline. */
export const DIGITVA_MIT_NOTICE = `MIT License

Copyright (c) 2026 Vivek Gupta

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.`;

export const SMARTVA_MIT_NOTICE = `MIT License

Copyright (c) 2018 University of Washington

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.`;

export const WHO_VA_NOTICE = `Independent implementation notice
=================================

This package is an independent software implementation of the 2022 WHO
verbal autopsy instrument. It is not affiliated with, sponsored by, or
endorsed by the World Health Organization (WHO). The name "WHO" is used only
to identify the source instrument. The WHO logo is not used and must not be
used to promote this package.

The MIT License in LICENSE applies to the original software implementation.
It does not replace or override the copyright or licence governing the source
questionnaire content.

Source instrument
-----------------

World Health Organization. 2022 WHO verbal autopsy instrument. Geneva: World
Health Organization; 2022.

https://www.who.int/publications/m/item/2022-who-verbal-autopsy-instrument

The source instrument is identified by WHO as licensed under Creative Commons
Attribution-NoDerivatives 3.0 IGO (CC BY-ND 3.0 IGO):

https://creativecommons.org/licenses/by-nd/3.0/igo/

Users remain responsible for complying with those terms, including attribution
and restrictions on adaptations. The base instrument uses the English source.

This experimental app also bundles Hindi questionnaire version 6, sourced from
ND01_ICMRVA_WHOVA2022.xlsx. It is not presented as an official WHO translation.
Its review and redistribution clearance remain pending. Missing Hindi text is
shown in English. Inclusion in this private test build does not authorize public
distribution of the translation.`;

export interface ThirdPartyNoticeBundle {
  generation: {
    npm_packages: number;
    rust_packages: number;
    rust_toolchain_entries: number;
    unique_notice_texts: number;
    packages_without_local_notice_text: number;
    rust_target: string;
  };
  package_notices: Array<{
    ecosystem: string;
    name: string;
    version: string;
    license: string;
    source: string;
    notice_status: string;
    notice_ids: string[];
  }>;
  notice_texts: Record<string, string>;
}

/** Format the generated lockfile inventory as one selectable, offline text block. */
export function formatThirdPartyNotices(bundle: ThirdPartyNoticeBundle): string {
  const { generation, package_notices: packages, notice_texts: noticeTexts } = bundle;
  const lines = [
    "Third-party software notices",
    "",
    `Scope: ${generation.npm_packages} Android-compatible non-development npm lockfile packages, ${generation.rust_packages} Rust crates for ${generation.rust_target}, and ${generation.rust_toolchain_entries} Rust standard-library entry.`,
    `The inventory contains ${generation.unique_notice_texts} unique notice texts. ${generation.packages_without_local_notice_text} packages have no readable notice text available in this checkout and are identified below.`,
    "This local inventory does not cover Android Gradle or Maven packages, WHO ICD-11 Classification Software, or other separately bundled runtimes. Review those items before release.",
    "",
    "PACKAGE INVENTORY",
  ];

  for (const item of packages) {
    lines.push(`${item.ecosystem}: ${item.name}@${item.version} — declared ${item.license}`);
    lines.push(`Source: ${item.source}`);
    if (item.notice_ids.length) {
      lines.push(`Bundled notice text: ${item.notice_ids.map((id) => id.slice(0, 12)).join(", ")}`);
    } else {
      lines.push(`NOTICE TEXT NOT FOUND LOCALLY: ${item.notice_status}`);
    }
  }

  lines.push("", "BUNDLED LICENSE AND NOTICE TEXTS");
  for (const id of Object.keys(noticeTexts).sort()) {
    lines.push("", `Notice ${id}:`, noticeTexts[id]);
  }
  return lines.join("\n");
}
