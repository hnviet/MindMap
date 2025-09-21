from pathlib import Path
text = Path('MindMap.py').read_text()
old = """    def _has_obstacle_between(
        self,
        pid: int,
        cid: int,
        start: Tuple[float, float],
        end: Tuple[float, float],
    ) -> bool:
        sx, sy = start
        ex, ey = end
        dx = ex - sx
        dy = ey - sy
        dist_sq = dx * dx + dy * dy
        if dist_sq < 1e-3:
            return False
        scale = self.ws.scale or 1.0
        node_radius = math.hypot(NODE_W * self.ws.scale / 2, NODE_H * self.ws.scale / 2) + NODE_MARGIN * self.ws.scale
"""
