from typing import Any, Dict, List


from lxml import etree


from abletools.api.plugin import Uid
from abletools.plugins.patch_registry import PatchRegistry
from abletools.utils.xml_converter import XMLConversionError, XMLConverter, copy_tags, find_not_null, format_long_text_element, make_tagged_value, map_tag


class VstConversionContext:
    def __init__(self, patch_registry: PatchRegistry, metadata: Dict[str, Any]):
        self._patch_registry = patch_registry
        self._metadata: Dict[str, Any] = metadata

    @property
    def patch_registry(self) -> PatchRegistry:
        return self._patch_registry

    @property
    def metadata(self) -> Dict[str, Any]:
        """Returns a copy of the metadata dictionary"""
        return dict(self._metadata)

    def get_meta(self, key: str) -> Any:
        return self._metadata[key]


class Vst3Converter(XMLConverter):
    # These tags are the same in VST2 and VST3 plugin info, so we can just copy them over without modification
    SAME_TAGS: List[str] = ["WinPosX", "WinPosY", "NumAudioInputs",
                            "NumAudioOutputs", "IsPlaceholderDevice"]

    def __init__(self, ctx: VstConversionContext):
        self.ctx = ctx

    def convert(self, root: etree.Element) -> etree.Element:
        # <Vst3PluginInfo Id="12345">
        vst3_info = etree.Element("Vst3PluginInfo")
        # IDK whether you can have more than one Vst3PluginInfo in a plugin descriptor tag
        vst3_info.set("Id", root.get("Id", "0"))

        # Copying these tags stricly causes errors when convertion older Live sets
        copy_tags(root, vst3_info, self.SAME_TAGS, strict=False)

        # <Preset Id="12345">
        vst3_info.append(VstPresetConverter(
            self.ctx).convert(find_not_null(root, "Preset/VstPreset")))

        # <Name>
        map_tag(root, vst3_info, "PlugName", "Name")

        # <Uid>
        vst3_info.append(_make_uid_element(
            self.ctx.get_meta("vst3_plugin_id")))

        return vst3_info


class VstPresetConverter(XMLConverter):
    # These go before the Processor and Controller states
    # I'm not sure if the order matters, but we might as well keep it consistent
    SAME_TAGS_1: List[str] = ["OverwriteProtectionNumber",
                              "MpeEnabled", "MpeSettings",
                              "ParameterSettings", "IsOn",
                              "PowerMacroControlIndex",
                              "PowerMacroMappingRange",
                              "IsFolded",
                              "StoredAllParameters",
                              "DeviceLomId",
                              "DeviceViewLomId",
                              "IsOnLomId",
                              "ParametersListWrapperLomId"]
    # These go after the Processor and Controller states
    SAME_TAGS_2: List[str] = ["Name", "PresetRef"]

    def __init__(self, ctx: VstConversionContext):
        self.ctx = ctx

    def convert(self, root: etree.Element) -> etree.Element:
        # root:
        #   <VstPreset Id="12345">
        #   ...
        #   </VstPreset>
        vst3_preset = etree.Element("Vst3Preset")
        vst3_preset.set("Id", root.get("Id", "0"))

        # First set of common tags
        copy_tags(root, vst3_preset, self.SAME_TAGS_1)

        # Add <Uid>
        vst3_preset.append(_make_uid_element(
            self.ctx.metadata["vst3_plugin_id"]))

        # TODO: Add <DeviceType>

        # Add <ProcessorState>
        plugin_data = VstPluginDataConverter(self.ctx).convert(
            find_not_null(root, "Buffer"))
        format_long_text_element(plugin_data)
        vst3_preset.append(plugin_data)

        # Add <ControllerState> (IDK whether this is supposed to have any contents)
        vst3_preset.append(etree.Element("ControllerState"))

        # Second set of common tags
        copy_tags(root, vst3_preset, self.SAME_TAGS_2)

        new_preset = etree.Element("Preset")
        new_preset.append(vst3_preset)
        return new_preset


class VstPluginDataConverter(XMLConverter):
    def __init__(self, ctx: VstConversionContext):
        self.ctx = ctx

    def convert(self, root: etree.Element) -> etree.Element:
        # root:
        #   <Buffer>
        #     ... (buffer data)
        #   </Buffer>
        buffer_contents = root.text
        if buffer_contents is None:
            raise XMLConversionError(
                f"Buffer contents for element '{root.getroottree().getpath(root)}' are empty.")

        buffer_contents = self.ctx.patch_registry.apply_user_patch(
            self._sanitize_buffer_contents(buffer_contents), self.ctx.metadata)

        vst3_state = etree.Element("ProcessorState")
        vst3_state.text = buffer_contents
        return vst3_state

    def _sanitize_buffer_contents(self, buffer_contents: str) -> str:
        # We need to remove spaces, newlines, tabs etc. so that binascii doesn't complain
        return "".join(buffer_contents.split())


def _make_uid_element(uid_fields: Uid) -> etree.Element:
    uid_element = etree.Element("Uid")
    for i, field in enumerate(uid_fields):
        uid_element.append(make_tagged_value(f"Fields.{i}", str(field)))
    return uid_element
