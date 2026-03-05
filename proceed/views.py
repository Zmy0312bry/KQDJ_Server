import asyncio
from datetime import datetime

import pytz
import requests
from django.db import models
from django.utils.decorators import method_decorator
from rest_framework.views import APIView

from utils.auth import auth
from utils.constance import *
from utils.env_loader import EnvVars
from utils.response import CustomResponse, CustomResponseSync

from .models import AllImageModel, MainForm
from .utils.handle_timestamp import timestamp_to_beijing_str


# 在创建Response时，要求必须包含一个message字段，用于返回操作结果
# 例如：return Response({'message': '操作成功'})
# 其他字段可以根据需要自行添加
# 建议所有接口数据通过Body返回
class UserFormFunctions(APIView):
    @method_decorator(auth.token_required)
    def post(self, request):
        # 使用同步方式调用异步方法
        async def _async_post():
            permission_level = request.permission_level
            user_openid = request.openid
            form_data = request.data
            form_images = request.data.get("form_images", [])
            print(form_images)
            source = "user" if permission_level == 0 else "admin"

            form = await self._create_form(
                form_data, form_images, source, user_openid=user_openid
            )
            return CustomResponseSync(data=form, message="表单创建成功")

        # 使用 sync_to_async 运行异步代码
        return asyncio.run(_async_post())

    async def _create_form(
        self, form_data, images=None, source="user", user_openid=None
    ):
        # 创建表单
        form = await MainForm.query_manager.create_form(
            form_data, images, source, user_openid=user_openid
        )
        return form

    @method_decorator(auth.token_required)
    def get(self, request):
        is_single = request.GET.get("uuid", None)
        finished = request.GET.get("finish", 0)
        if not is_single:
            # 获取所有表单
            return CustomResponse(
                self._get_multi_pages, request, openid=request.openid, finished=finished
            )
        else:
            # 获取单个表单
            return CustomResponse(self._get_single_page, is_single)

    def _get_multi_pages(self, request, openid, finished):
        mainform_queryset = MainForm.query_manager.filter_by_openid(openid).filter(
            handle=finished
        )
        is_dispatch = request.GET.get("is_dispatch")
        if is_dispatch == "0":
            mainform_queryset = mainform_queryset.filter(orders__isnull=True, handle=0)
        elif is_dispatch == "1":
            mainform_queryset = mainform_queryset.filter(
                models.Q(orders__isnull=False) | ~models.Q(handle=0)
            ).distinct()
        if not mainform_queryset.exists():
            raise Exception("对应表单不存在")
        return mainform_queryset.order_by("-upload_time").paginate(request, simple=True)

    def _get_single_page(self, is_pk):
        return MainForm.query_manager.get_queryset().filter(uuidx=is_pk).serialize()

    @method_decorator(auth.token_required)
    def patch(self, request):
        is_pk = request.GET.get("uuid", None)
        if not is_pk:
            raise Exception("uuid不能为空")
        return CustomResponse(self._update_form, request, is_pk)

    def _update_form(self, request, is_pk):
        evaluate_info = request.data
        print(evaluate_info)
        form_evaulation = MainForm.objects.filter(uuidx=is_pk).first()
        form_evaulation.update_form(
            evaluation_info=evaluate_info
        )  # 更新表单状态为已评价
        from .serializers import MainFormSerializer

        return {"message": "评价成功", "data": MainFormSerializer(form_evaulation).data}


class AdminFormFunctions(APIView):
    # 拉起表单(单表单和多表单)
    @method_decorator(
        auth.token_required(
            required_permission=[ADMIN_USER, SUPER_ADMIN_USER, PROPERTY_STAFF]
        )
    )
    def get(self, request):
        is_pk = request.GET.get("uuid", None)  # 无pk无finish为历史记录
        finished = request.GET.get("finish", 3)
        if not is_pk:
            # 获取所有表单
            return CustomResponse(
                self._admin_get_multi_forms, request, finished=finished
            )
        else:
            # 获取单个表单详情
            return CustomResponse(self._admin_get_single_form, is_pk)

    def _admin_get_single_form(self, is_pk):
        form = MainForm.query_manager.get_queryset().filter(uuidx=is_pk)
        if not form:
            raise Exception("表单不存在")
        return form.serialize()

    def _admin_get_multi_forms(self, request, finished):
        if finished == 3:
            form = MainForm.query_manager.get_queryset()
        else:
            form = MainForm.query_manager.get_queryset().filter(handle=finished)
        is_dispatch = request.GET.get("is_dispatch")
        if is_dispatch == "0":
            form = form.filter(orders__isnull=True, handle=0)
        elif is_dispatch == "1":
            form = form.filter(
                models.Q(orders__isnull=False) | ~models.Q(handle=0)
            ).distinct()
        if not form:
            raise Exception("表单不存在")
        return form.order_by("-upload_time").paginate(request, simple=True)

    # 处理一个表单
    @method_decorator(
        auth.token_required(
            required_permission=[ADMIN_USER, SUPER_ADMIN_USER, PROPERTY_STAFF]
        )
    )
    def put(self, request):
        is_pk = request.GET.get("uuid", None)
        if not is_pk:
            raise Exception("表单UUID不能为空")

        return CustomResponse(self._handle_a_form, request, is_pk)

    def _handle_a_form(self, request, is_pk):
        update_info = request.data
        form_images = request.data.get("handle_images", [])
        form = MainForm.objects.filter(uuidx=is_pk).first()

        if not form:
            raise Exception("表单不存在")
        # update_info["admin_openid"] = openid
        # 更新表单状态和管理员处理信息
        form.update_form(handle_images=form_images, handle_info=update_info)

        from .serializers import MainFormSerializer

        return {"message": "表单处理成功", "data": MainFormSerializer(form).data}

    # 删除表单
    @method_decorator(auth.token_required(required_permission=[SUPER_ADMIN_USER]))
    def delete(self, request):
        return CustomResponse(self._delete_a_form, request)

    def _delete_a_form(self, request):
        # 从请求体中获取要删除的表单ID列表
        form_ids = request.GET.get("uuid", None)

        if not form_ids:
            raise Exception("未指定要删除的表单UUID")

        # 删除表单
        try:
            form = MainForm.objects.get(uuidx=form_ids)
            form_info = {
                "uuid": form_ids,
                "title": getattr(form, "title", f"表单-{form_ids}"),
            }
            form.delete()
        except MainForm.DoesNotExist:
            raise Exception("表单不存在")
        except Exception as e:
            raise Exception(f"删除表单失败: {str(e)}")

        return {
            "message": "表单删除成功",
            "data": form_info,
        }


class AdminFormHandleFunctions(APIView):
    # 获取待回访表单
    @method_decorator(
        auth.token_required(
            required_permission=[ADMIN_USER, SUPER_ADMIN_USER, PROPERTY_STAFF]
        )
    )
    def get(self, request):
        return CustomResponse(self._admin_get_multi_forms, request)

    def _admin_get_multi_forms(self, request):
        form = MainForm.query_manager.feedback_needed()
        if not form:
            raise Exception("表单不存在")
        return form.order_by("-upload_time").paginate(request, simple=True)

    # 处理一个表单
    @method_decorator(
        auth.token_required(
            required_permission=[ADMIN_USER, SUPER_ADMIN_USER, PROPERTY_STAFF]
        )
    )
    def put(self, request):
        is_pk = request.GET.get("uuid", None)
        if not is_pk:
            raise Exception("表单UUID不能为空")

        return CustomResponse(self._handle_a_form, request, is_pk)

    def _handle_a_form(self, request, is_pk):
        update_info = request.data
        form_images = request.data.get("handle_images", [])
        form = MainForm.objects.filter(uuidx=is_pk).first()

        if not form:
            raise Exception("表单不存在")

        # 更新表单状态和管理员处理信息
        form.update_form(handle_images=form_images, feedback_info=update_info)

        from .serializers import MainFormSerializer

        return {"message": "表单处理成功", "data": MainFormSerializer(form).data}


class ImageUploadAPI(APIView):
    """
    图片上传接口
    POST: 上传图片并返回保存路径
    """

    @method_decorator(auth.token_required)
    def post(self, request):
        return CustomResponse(self._upload_image, request)

    def _upload_image(self, request):
        openid = request.openid
        # 检查是否有文件上传
        if not request.FILES or "file" not in request.FILES:
            raise Exception("没有找到上传的图片")

        image_file = request.FILES["file"]
        from user.models import Users

        user_permission = Users.query_manager.get_permission_level(openid)
        source = "admin" if user_permission > 0 else "user"
        # 创建并保存图片
        image_model = AllImageModel(image=image_file, source=source)
        image_model.save()

        # 获取保存的路径
        image_path = (
            image_model.image.url
            if hasattr(image_model.image, "url")
            else str(image_model.image)
        )

        return {"path": image_path, "message": "图片上传成功"}


class List2Excel(APIView):
    @method_decorator(
        auth.token_required(required_permission=[ADMIN_USER, SUPER_ADMIN_USER])
    )
    def post(self, request):
        data = request.data
        start_date = data.get("start_time", "")
        end_date = data.get("end_time", "")
        try:
            from .utils.handle_timestamp import process_date_range

            start_timestamp, end_timestamp = process_date_range(start_date, end_date)
            return MainForm.export_to_excel(start_timestamp, end_timestamp)

        except Exception as e:
            raise Exception(str(e))


class DispatchOrder(APIView):
    """
    派单接口
    POST: 向指定用户发送工单订阅消息
    GET: 获取当前用户的派单记录
    """

    @method_decorator(
        auth.token_required(
            required_permission=[
                ADMIN_USER,
                SUPER_ADMIN_USER,
                GRID_WORKER,
                PROPERTY_STAFF,
            ]
        )
    )
    def get(self, request):
        """获取派单记录"""
        return CustomResponse(self._get_dispatch_orders, request)

    @method_decorator(
        auth.token_required(required_permission=[ADMIN_USER, SUPER_ADMIN_USER])
    )
    def post(self, request):
        return CustomResponse(self._dispatch_order, request)

    def _get_dispatch_orders(self, request):
        """获取当前用户的派单记录"""
        openid = request.openid
        from .models import Order

        # 查询该派单员的所有派单记录
        orders_queryset = Order.query_manager.filter_by_openid(openid)

        if not orders_queryset.exists():
            return {"total": 0, "results": [], "message": "暂无派单记录"}

        return orders_queryset.paginate(request)

    def _dispatch_order(self, request):
        # 从查询参数获取openid和uuidx
        openid = request.GET.get("openid")
        uuidx = request.GET.get("uuidx")

        # 参数验证
        if not openid:
            raise Exception("openid参数不能为空")
        if not uuidx:
            raise Exception("uuidx参数不能为空")

        # 查询表单数据
        try:
            form = MainForm.objects.get(uuidx=uuidx)
        except MainForm.DoesNotExist:
            raise Exception("找不到对应的表单")

        # 已派单校验
        if form.orders.exists():
            raise Exception("该表单已派单，不能重复派单")

        # 已处理校验
        if form.handle != 0:
            raise Exception("该表单已被处理，不能派单")

        # 提取需要的字段
        serial_number = form.serial_number
        category = form.category
        upload_time = form.upload_time
        title = form.title

        # 验证必要字段
        if not serial_number:
            raise Exception("表单序号为空，无法派单")
        if not title:
            raise Exception("表单标题为空，无法派单")

        # 获取access_token
        print(f"[派单流程] 开始派单: openid={openid}, uuidx={uuidx}, title={title}")
        access_token = self._get_access_token()

        # 发送订阅消息
        result = self._send_subscribe_message(
            access_token=access_token,
            openid=openid,
            title=title,
        )

        # 派单成功后，创建派单记录
        from .models import Order

        Order.objects.create(
            main_form=form,
            serial_number=serial_number,
            title=title,
            dispatch_openid=openid,
        )

        print(f"[派单流程] 派单完成，已创建派单记录")
        return result

    def _get_access_token(self):
        """获取微信access_token"""
        env = EnvVars()
        appid = env.APP_ID
        secret = env.APP_SECRET

        url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appid}&secret={secret}"

        print(f"[微信接口] 获取access_token请求URL: {url}")

        try:
            response = requests.get(url, timeout=10)
            print(f"[微信接口] 获取access_token响应状态码: {response.status_code}")
            print(f"[微信接口] 获取access_token响应内容: {response.text}")

            response.raise_for_status()
            data = response.json()

            if "access_token" not in data:
                error_msg = data.get("errmsg", "未知错误")
                print(f"[微信接口] 获取access_token失败: {error_msg}")
                raise Exception(f"获取access_token失败: {error_msg}")

            print(f"[微信接口] 获取access_token成功")
            return data["access_token"]
        except requests.RequestException as e:
            print(f"[微信接口] 请求微信接口异常: {str(e)}")
            raise Exception(f"请求微信接口失败: {str(e)}")

    def _send_subscribe_message(self, access_token, openid, title):
        """发送订阅消息"""
        url = f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={access_token}"

        # 获取当前时间（派单时间）
        beijing_tz = pytz.timezone("Asia/Shanghai")
        current_time = datetime.now(beijing_tz)
        dispatch_time = current_time.strftime("%Y年%m月%d日 %H:%M")

        # 构建请求体
        message_data = {
            "template_id": "QSW5PvhHb9ENbmhHgQCCEC72XuZoYU-uz7uaHsMkZcQ",
            "touser": openid,
            "data": {
                "thing2": {
                    "value": title[:20]  # 微信限制最多20个字符
                },
                "time3": {"value": dispatch_time},
                "thing4": {"value": "请迅速处理派单"},
            },
            "miniprogram_state": "formal",
            "lang": "zh_CN",
        }

        print(f"[微信接口] 发送订阅消息请求URL: {url}")
        print(f"[微信接口] 发送订阅消息请求体: {message_data}")

        try:
            response = requests.post(url, json=message_data, timeout=10)
            print(f"[微信接口] 发送订阅消息响应状态码: {response.status_code}")
            print(f"[微信接口] 发送订阅消息响应内容: {response.text}")

            response.raise_for_status()
            result = response.json()

            errcode = result.get("errcode")
            print(f"[微信接口] 错误码: {errcode}")

            if errcode == 0:
                print(f"[微信接口] 发送订阅消息成功: openid={openid}, title={title}")
                return {
                    "message": "派单成功",
                    "title": title,
                    "recipient": openid,
                }
            else:
                error_msg = result.get("errmsg", "未知错误")
                print(
                    f"[微信接口] 发送订阅消息失败: errcode={errcode}, errmsg={error_msg}"
                )
                raise Exception(f"发送订阅消息失败: {error_msg}")
        except requests.RequestException as e:
            print(f"[微信接口] 请求微信接口异常: {str(e)}")
            raise Exception(f"请求微信接口失败: {str(e)}")
