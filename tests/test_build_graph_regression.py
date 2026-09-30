import unittest

from pbi_usage_analyzer.model import (
    DependencyGraph,
    ModelObject,
    ObjectRef,
    ObjectType,
)


class BuildGraphRegressionTests(unittest.TestCase):
    def test_query_objects_can_be_added_after_model_iteration(self):
        graph = DependencyGraph()
        table = ObjectRef(ObjectType.TABLE, "Hovedbok")
        column = ObjectRef(ObjectType.COLUMN, "Hovedbok", "beløp")
        graph.add_object(ModelObject(ref=table))
        graph.add_object(ModelObject(ref=column))

        query_objects = []
        for ref, obj in list(graph.objects.items()):
            if ref.object_type == ObjectType.TABLE:
                query_objects.append(
                    ModelObject(
                        ref=ObjectRef(ObjectType.QUERY, ref.table),
                        source_file=obj.source_file,
                    )
                )

        graph.add_objects(query_objects)

        self.assertIn(
            ObjectRef(ObjectType.QUERY, "Hovedbok"),
            graph.objects,
        )


if __name__ == "__main__":
    unittest.main()
