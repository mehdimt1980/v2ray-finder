package org.mehdimt.v2rayfinder.runtime.xray

import org.json.JSONObject

/** Result of converting one proxy URI into an xray outbound JSON object. */
data class XrayOutboundConversion(
    val protocol: String,
    val outbound: JSONObject,
)

/** Result of building a full xray config for one proxy URI. */
data class XrayConfigBuildResult(
    val config: String,
    val protocol: String,
    val socksPort: Int,
    val xrayConfigJson: String,
)
