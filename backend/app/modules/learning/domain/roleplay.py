"""Server-owned situations for one learner and Tata, with a goal for either role."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    id: str
    title: tuple[str, str, str]
    context: tuple[str, str, str]
    roles: tuple[tuple[str, str], tuple[str, str], tuple[str, str]]
    goals: tuple[tuple[str, str], tuple[str, str], tuple[str, str]]

    def view(self, support: str) -> dict:
        index = 1 if support == "vi" else 2 if support == "zh" else 0
        return {"id": self.id, "title": self.title[index], "context": self.context[index],
                "roles": list(self.roles[index]), "goals": list(self.goals[index])}


SCENARIOS = (
    Scenario("hotel", ("Missing hotel reservation", "Không tìm thấy đặt phòng", "找不到酒店预订"),
        ("A guest arrives at a hotel, but the reservation cannot be found.",
         "Khách đến khách sạn nhưng nhân viên chưa tìm thấy đặt phòng.", "客人到酒店后，前台找不到预订。"),
        (("Guest", "Receptionist"), ("Khách", "Lễ tân"), ("客人", "前台")),
        (("Confirm your booking and agree on a suitable room.", "Check the booking and offer a suitable solution."),
         ("Xác nhận đặt phòng và thống nhất phòng phù hợp.", "Kiểm tra đặt phòng và đề xuất cách giải quyết phù hợp."),
         ("确认预订并商定合适的房间。", "核实预订并提出合适的解决办法。"))),
    Scenario("restaurant", ("Ordering a meal", "Gọi món tại nhà hàng", "在餐厅点餐"),
        ("A customer needs to order a meal and ask about ingredients.",
         "Khách muốn gọi món và hỏi về thành phần món ăn.", "顾客想点餐并询问食材。"),
        (("Customer", "Waiter"), ("Khách", "Nhân viên phục vụ"), ("顾客", "服务员")),
        (("Ask about ingredients and agree on a suitable order.", "Explain the options and confirm the order."),
         ("Hỏi thành phần và chọn món phù hợp.", "Giải thích lựa chọn và xác nhận món khách gọi."),
         ("询问食材并选好餐点。", "介绍选择并确认点餐。"))),
    Scenario("interview", ("Job interview", "Phỏng vấn công việc", "工作面试"),
        ("An applicant and interviewer discuss experience and a possible job.",
         "Ứng viên và người phỏng vấn trao đổi về kinh nghiệm và công việc.", "应聘者与面试官讨论经验和工作。"),
        (("Applicant", "Interviewer"), ("Ứng viên", "Người phỏng vấn"), ("应聘者", "面试官")),
        (("Explain your experience and ask about the work.", "Ask about relevant experience and explain the work."),
         ("Trình bày kinh nghiệm và hỏi về công việc.", "Hỏi kinh nghiệm liên quan và giải thích công việc."),
         ("介绍经验并询问工作内容。", "了解相关经验并介绍工作。"))),
)


def find_scenario(scenario_id: str) -> Scenario | None:
    return next((scenario for scenario in SCENARIOS if scenario.id == scenario_id), None)


def roleplay_instruction(scenario_id: str | None, swapped: bool = False) -> str:
    scenario = find_scenario(scenario_id) if scenario_id else None
    if scenario is None:
        return ""
    learner, agent = (1, 0) if swapped else (0, 1)
    return (f"\nROLEPLAY (server-owned instructions): {scenario.context[0]} "
            f"The learner is the {scenario.roles[0][learner]}; you, Tata, play the {scenario.roles[0][agent]}. "
            f"Learner goal: {scenario.goals[0][learner]} Your character's goal: {scenario.goals[0][agent]} "
            "This replaces the free-conversation invitation to change topics. Stay in this situation, "
            "react to what the learner actually says, and let the outcome develop naturally. "
            "Do not invent personal details or a fixed answer the learner must recite. "
            "Do not speak the learner's lines. Ask at most one short question at a time. "
            "When the learner asks for help, use the existing on-screen support ladder, then resume your role. "
            "Do not interrupt for every small error or claim the goal was achieved without conversational evidence.")
