import unittest

from vision.ppe_vision import Detection, associate_equipment


class AssociateEquipmentTests(unittest.TestCase):
    def test_pairs_helmet_and_vest_to_person(self):
        person = Detection("person", 0.9, (100, 50, 200, 350))
        items = [
            Detection("safety_helmet", 0.88, (130, 55, 165, 95)),
            Detection("reflective_jacket", 0.91, (115, 130, 188, 240)),
        ]
        result = associate_equipment([person], items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "compliant")
        self.assertTrue(result[0].helmet_detected)
        self.assertTrue(result[0].vest_detected)

    def test_missing_item_is_indeterminate_not_violation(self):
        person = Detection("person", 0.9, (100, 50, 200, 350))
        items = [Detection("safety_helmet", 0.88, (130, 55, 165, 95))]
        result = associate_equipment([person], items)[0]
        self.assertEqual(result.status, "indeterminate")
        self.assertEqual(result.reasons, ("vest_not_detected",))

    def test_small_person_is_indeterminate_even_when_items_detected(self):
        person = Detection("person", 0.9, (100, 50, 160, 100))
        items = [
            Detection("safety_helmet", 0.88, (115, 50, 140, 68)),
            Detection("reflective_jacket", 0.91, (106, 63, 155, 92)),
        ]
        result = associate_equipment([person], items, min_person_height=80)[0]
        self.assertEqual(result.status, "indeterminate")
        self.assertIn("person_too_small_for_reliable_assessment", result.reasons)

    def test_ambiguous_equipment_is_not_assigned_to_both_people(self):
        people = [
            Detection("person", 0.9, (100, 50, 200, 350)),
            Detection("person", 0.9, (120, 50, 220, 350)),
        ]
        helmet = Detection("safety_helmet", 0.88, (140, 55, 170, 90))
        result = associate_equipment(people, [helmet])
        self.assertTrue(all(not item.helmet_detected for item in result))
        self.assertTrue(all("helmet_ambiguous" in item.reasons for item in result))

    def test_multiple_people_receive_their_own_equipment(self):
        people = [
            Detection("person", 0.9, (20, 40, 100, 300)),
            Detection("person", 0.9, (180, 40, 260, 300)),
        ]
        equipment = [
            Detection("safety_helmet", 0.9, (38, 45, 65, 75)),
            Detection("reflective_jacket", 0.9, (30, 95, 90, 180)),
            Detection("safety_helmet", 0.9, (198, 45, 225, 75)),
            Detection("reflective_jacket", 0.9, (190, 95, 250, 180)),
        ]
        result = associate_equipment(people, equipment)
        self.assertEqual([item.status for item in result], ["compliant", "compliant"])

    def test_negative_class_is_not_counted_as_worn_equipment(self):
        person = Detection("person", 0.9, (100, 50, 200, 350))
        negative = Detection("no_helmet", 0.99, (130, 55, 165, 95))
        result = associate_equipment([person], [negative])[0]
        self.assertFalse(result.helmet_detected)
        self.assertEqual(result.status, "indeterminate")


if __name__ == "__main__":
    unittest.main()
