// mascot.jsx — 旅行向导小人「途途」
// 用法: <Mascot size={160} pose="wave" />  pose: idle | wave | walk | point | cheer | think
// 颜色来自主题 CSS 变量 --mascot-skin / --mascot-hat / --mascot-coat / --mascot-scarf

function Mascot({ size = 140, pose = "idle", flip = false, style = {} }) {
  const id = React.useId().replace(/:/g, "");
  return (
    <div
      className={`mascot mascot-${pose}`}
      style={{ width: size, height: size * 1.18, flexShrink: 0, ...style, transform: flip ? "scaleX(-1)" : undefined }}
      aria-label="旅行向导小人"
      role="img"
    >
      <style>{`
        .mascot svg { width: 100%; height: 100%; display: block; overflow: visible; }
        .mascot .m-body-grp { transform-origin: 60px 120px; }
        .mascot .m-arm-r { transform-origin: 78px 78px; }
        .mascot .m-arm-l { transform-origin: 42px 78px; }
        .mascot .m-leg-l { transform-origin: 52px 116px; }
        .mascot .m-leg-r { transform-origin: 68px 116px; }
        .mascot .m-eyes { transform-origin: 60px 52px; animation: m-blink 4.2s infinite; }
        .mascot .m-flag { transform-origin: 84px 58px; }
        .mascot .m-shadow { transform-origin: 60px 142px; }
        @keyframes m-blink { 0%, 94%, 100% { transform: scaleY(1); } 96.5% { transform: scaleY(.12); } }

        @media (prefers-reduced-motion: no-preference) {
          .mascot-idle .m-body-grp, .mascot-wave .m-body-grp, .mascot-point .m-body-grp, .mascot-think .m-body-grp {
            animation: m-bob 3.2s ease-in-out infinite;
          }
          @keyframes m-bob { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-3px); } }

          .mascot-wave .m-arm-r { animation: m-wave 1.6s ease-in-out infinite; }
          @keyframes m-wave { 0%,100% { transform: rotate(-58deg); } 50% { transform: rotate(-22deg); } }

          .mascot-walk .m-body-grp { animation: m-trot .55s ease-in-out infinite; }
          @keyframes m-trot { 0%,100% { transform: translateY(0) rotate(1.2deg); } 50% { transform: translateY(-4px) rotate(-1.2deg); } }
          .mascot-walk .m-leg-l { animation: m-step .55s ease-in-out infinite; }
          .mascot-walk .m-leg-r { animation: m-step .55s ease-in-out infinite reverse; }
          @keyframes m-step { 0%,100% { transform: rotate(24deg); } 50% { transform: rotate(-24deg); } }
          .mascot-walk .m-arm-l { animation: m-swing .55s ease-in-out infinite; }
          @keyframes m-swing { 0%,100% { transform: rotate(-18deg); } 50% { transform: rotate(18deg); } }

          .mascot-cheer .m-arm-r { animation: m-cheer-r 1s ease-in-out infinite; }
          .mascot-cheer .m-arm-l { animation: m-cheer-l 1s ease-in-out infinite; }
          @keyframes m-cheer-r { 0%,100% { transform: rotate(-50deg); } 50% { transform: rotate(-66deg); } }
          @keyframes m-cheer-l { 0%,100% { transform: rotate(50deg); } 50% { transform: rotate(66deg); } }
          .mascot-cheer .m-body-grp { animation: m-hop .9s ease-in-out infinite; }
          @keyframes m-hop { 0%,100% { transform: translateY(0); } 40% { transform: translateY(-7px); } }

          .mascot-think .m-flag { animation: m-tilt 2.6s ease-in-out infinite; }
          @keyframes m-tilt { 0%,100% { transform: rotate(0deg); } 50% { transform: rotate(6deg); } }
        }
      `}</style>
      <svg viewBox="0 0 120 150">
        {/* 地面阴影 */}
        <ellipse className="m-shadow" cx="60" cy="142" rx="26" ry="5" fill="currentColor" opacity=".1" />

        <g className="m-body-grp">
          {/* 背包 */}
          <rect x="24" y="74" width="22" height="30" rx="9" fill="var(--mascot-scarf)" opacity=".92" />
          <rect x="28" y="80" width="14" height="7" rx="3.5" fill="var(--mascot-hat)" />

          {/* 左臂(后) */}
          <g className="m-arm-l" style={pose === "point" ? { transform: "rotate(8deg)" } : undefined}>
            <rect x="36" y="76" width="9" height="26" rx="4.5" fill="var(--mascot-coat)" />
            <circle cx="40.5" cy="101" r="4.6" fill="var(--mascot-skin)" />
          </g>

          {/* 腿 */}
          <g className="m-leg-l">
            <rect x="47" y="112" width="9.5" height="22" rx="4.7" fill="#3a3530" />
            <ellipse cx="51" cy="135" rx="7.5" ry="4.6" fill="#23201c" />
          </g>
          <g className="m-leg-r">
            <rect x="63.5" y="112" width="9.5" height="22" rx="4.7" fill="#3a3530" />
            <ellipse cx="69" cy="135" rx="7.5" ry="4.6" fill="#23201c" />
          </g>

          {/* 身体外套 */}
          <path d="M40 84 q0 -14 20 -14 q20 0 20 14 l1.5 26 q0 8 -21.5 8 q-21.5 0 -21.5 -8 z" fill="var(--mascot-coat)" />
          {/* 口袋缝线 */}
          <line x1="60" y1="92" x2="60" y2="114" stroke="rgba(0,0,0,.18)" strokeWidth="1.6" />
          <circle cx="55" cy="98" r="1.5" fill="rgba(255,255,255,.55)" />
          <circle cx="55" cy="106" r="1.5" fill="rgba(255,255,255,.55)" />

          {/* 围巾 */}
          <path d="M42 76 q18 9 36 0 l-2 7 q-16 7.5 -32 0 z" fill="var(--mascot-scarf)" />
          <rect x="64" y="80" width="8" height="16" rx="4" fill="var(--mascot-scarf)" />

          {/* 头 */}
          <circle cx="60" cy="52" r="24" fill="var(--mascot-skin)" />
          {/* 表情 */}
          <g className="m-eyes">
            {pose === "think" ? (
              <g>
                <circle cx="51" cy="54" r="2.6" fill="#2a221a" />
                <circle cx="69" cy="54" r="2.6" fill="#2a221a" />
              </g>
            ) : (
              <g>
                <circle cx="51" cy="53" r="3" fill="#2a221a" />
                <circle cx="69" cy="53" r="3" fill="#2a221a" />
                <circle cx="52.2" cy="51.8" r="1" fill="#fff" />
                <circle cx="70.2" cy="51.8" r="1" fill="#fff" />
              </g>
            )}
            {pose === "cheer" ? (
              <path d="M53 62 q7 7 14 0 q-7 3.4 -14 0 z" fill="#a14a3a" />
            ) : pose === "think" ? (
              <path d="M55 63 q5 -2.5 10 0" stroke="#a14a3a" strokeWidth="2" fill="none" strokeLinecap="round" />
            ) : (
              <path d="M54 61 q6 5 12 0" stroke="#a14a3a" strokeWidth="2.2" fill="none" strokeLinecap="round" />
            )}
            <ellipse cx="44" cy="59" rx="3.6" ry="2.2" fill="#e98c6b" opacity=".5" />
            <ellipse cx="76" cy="59" rx="3.6" ry="2.2" fill="#e98c6b" opacity=".5" />
          </g>

          {/* 遮阳帽 */}
          <path d="M31 42 q29 -10 58 0 q-3 4 -8 4.5 q-21 4 -42 0 q-5 -.5 -8 -4.5 z" fill="var(--mascot-hat)" />
          <path d="M40 42 q2 -17 20 -17 q18 0 20 17 q-20 5 -40 0 z" fill="var(--mascot-hat)" />
          <path d="M40 40.5 q20 4.5 40 0 l-.6 3 q-19.4 4.2 -38.8 0 z" fill="var(--mascot-coat)" opacity=".85" />

          {/* 右臂(前): wave 举手 / point 持小旗 / 其它下垂 */}
          <g
            className="m-arm-r"
            style={
              pose === "point" ? { transform: "rotate(-34deg)" }
              : pose === "walk" ? { transform: "rotate(14deg)" }
              : pose === "wave" || pose === "cheer" ? undefined
              : { transform: "rotate(6deg)" }
            }
          >
            <rect x="74" y="76" width="9" height="26" rx="4.5" fill="var(--mascot-coat)" />
            <circle cx="78.5" cy="101" r="4.6" fill="var(--mascot-skin)" />
            {(pose === "point" || pose === "walk") && (
              <g className="m-flag">
                <line x1="78.5" y1="101" x2="78.5" y2="62" stroke="#7a6a52" strokeWidth="2.6" strokeLinecap="round" />
                <path d="M79.5 62 l20 5 -20 5 z" fill="var(--mascot-hat)" />
              </g>
            )}
          </g>
        </g>
      </svg>
    </div>
  );
}

Object.assign(window, { Mascot });
